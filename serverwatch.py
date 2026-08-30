# -*- coding: utf-8 -*-
"""サーバーの死活監視（EOS）。

ASA は A2S を喋らないので、Epic に登録されているセッション情報を見る（eos.py）。
IPとポートを覚えておけば、そのサーバーが今起きているか・何人いるか・
ARKの「Day N」がいくつかが分かる。

分かることの使いみち:
  * 落ちている間はゲーム内時間も止まるので、その間だけ時計を止める
  * Day が増えた瞬間 = ゲーム内の日付が変わった瞬間。これを2回つかまえれば
    「ゲーム内1日 = 実何分か」がそのまま測れるし、時計の合わせ直しにも使える
"""
from __future__ import annotations

import threading
import time

import eos


def fmt_uptime(sec):
    """継続稼働時間の見せ方。長くなるので日・時間・分まで。"""
    sec = int(max(0, sec))
    d, rem = divmod(sec, 86400)
    h, m = divmod(rem // 60, 60)
    if d:
        return "%d日%d時間" % (d, h)
    if h:
        return "%d時間%d分" % (h, m)
    return "%d分" % m


class Watcher(threading.Thread):
    """登録されたサーバーを順に見て、状態を覚えておくスレッド。

    get_targets() は [(キー, "IP:ポート"), ...] を返す関数。
    生死やDayの変化は on_event(キー, 種類, 値) で知らせる。
      種類 "down" … 落ちた（値は最後に生きているのを見た時刻）
      種類 "up"   … 戻った（値はその時刻）
      種類 "day"  … Dayが増えた（値は (前のDay, 新しいDay, 前回増えた時刻)）
    """

    def __init__(self, get_targets, on_event=None, interval=60.0,
                 get_interval=None):
        super().__init__(daemon=True)
        self.get_targets = get_targets
        # 次まで何秒待つかを毎回決める関数（再起動の前後だけ短くする用）
        self.get_interval = get_interval
        self.on_event = on_event
        self.interval = float(interval)
        self._halt = threading.Event()
        self._wake = threading.Event()   # 「いま見に行く」で叩く
        self.client = eos.Client()
        self.state = {}        # キー -> 最後に見た結果
        self._last_seen = {}   # キー -> 最後に確認した時刻
        self._day_at = {}      # キー -> そのDayになった時刻
        self._online_at = {}   # キー -> 最後に「起きている」のを見た時刻
        # キー -> (起きているのを最初に見た時刻, 立ち上がる瞬間を見たか)
        # 落ちたら捨てる。定期再起動でもクラッシュでも同じ扱い。
        self._up_since = {}

    def stop(self):
        self._halt.set()
        self._wake.set()

    def poke(self):
        """待ちを打ち切って、次の見回りをすぐ始めさせる。"""
        self._wake.set()

    # ---- 1件ぶんの問い合わせ ----
    def check_now(self, key, address):
        ip, port = eos.parse_address(address)
        if not ip:
            return {"ok": False, "why": "アドレスの書き方が違います（例 1.2.3.4:7980）",
                    "online": False, "at": time.time()}
        try:
            sessions = self.client.sessions_by_address(ip)
        except eos.EosError as e:
            return {"ok": False, "why": str(e)[:90], "online": False,
                    "at": time.time()}
        if not sessions:
            return {"ok": True, "why": "そのIPにサーバーが見つかりません",
                    "online": False, "at": time.time(), "sessions": []}
        hit = None
        if port:
            hit = next((s for s in sessions if s["port"] == port), None)
        else:
            hit = sessions[0]
        if hit is None:
            return {"ok": True, "why": "そのポートのサーバーが見つかりません",
                    "online": False, "at": time.time(), "sessions": sessions}
        out = dict(hit)
        out.update({"ok": True, "online": True, "at": time.time(),
                    "sessions": sessions})
        return out

    def uptime(self, key, now=None):
        """そのサーバーが続けて起きている秒数と、それが正確かどうか。

        戻り値 (秒, 正確か)。落ちるとリセットされるので、定期再起動でも
        クラッシュでも 0 から数え直しになる。見つからなければ (None, False)。
        """
        got = self._up_since.get(key)
        if not got:
            return None, False
        since, exact = got
        return max(0.0, (now or time.time()) - since), exact

    def day_at(self, key):
        """そのマップで前に Day が変わった時刻。まだ見ていなければ None。

        「あと何分で測り終わるか」を出すのに使う。
        """
        return self._day_at.get(key)

    def list_servers(self, address):
        """そのIPにあるサーバー一覧（マップを選ばせる用）。"""
        ip, _ = eos.parse_address(address)
        if not ip:
            return []
        try:
            return self.client.sessions_by_address(ip)
        except eos.EosError:
            return []

    def search(self, text):
        """名前かIPで探す。数字とドットだけならIPとみなす。

        戻り値は [{name, map, players, ip, port, ...}, ...]。
        """
        t = (text or "").strip()
        if not t:
            return []
        head = t.replace(":", " ").split()[0]
        looks_ip = head.replace(".", "").isdigit() and head.count(".") == 3
        try:
            if looks_ip:
                found = self.client.sessions_by_address(head)
                for s in found:
                    s["ip"] = head
                return found
            return self.client.sessions_by_name(t)
        except eos.EosError:
            return []

    # ---- 見張る ----
    def run(self):
        while not self._halt.is_set():
            for key, address in (self.get_targets() or []):
                if self._halt.is_set():
                    break
                self._check_one(key, address)
            self._wake.wait(self.next_wait())
            self._wake.clear()

    def next_wait(self):
        """次の見回りまで何秒待つか。"""
        if self.get_interval is not None:
            try:
                return max(5.0, float(self.get_interval()))
            except Exception:
                pass
        return max(20.0, self.interval)

    def _check_one(self, key, address):
        res = self.check_now(key, address)
        prev = self.state.get(key)
        now = res.get("at") or time.time()

        # 生死が変わった瞬間だけ知らせる。落ちたら時計を止め、戻したら
        # 止まっていたぶんを差し引く。毎回 hold を送る昔のやり方だと、
        # 見回りと見回りの間（既定60秒）は時計が進みっぱなしになっていた。
        online = bool(res.get("online"))
        was = bool((prev or {}).get("online"))
        if self.on_event:
            if not online and (prev is None or was):
                self._fire(key, "down", self._online_at.get(key) or now)
            elif online and prev is not None and not was:
                self._fire(key, "up", now)
        if online:
            self._online_at[key] = now
            if key not in self._up_since:
                # 落ちてから戻ったのを見たなら、その時刻が本当の起動時刻。
                # 見張りはじめて最初から起きていた場合は「それ以上」しか言えない。
                self._up_since[key] = (now, prev is not None and not was)
        else:
            self._up_since.pop(key, None)

        # Day が増えたら知らせる（前に増えた時刻も一緒に）
        day = res.get("day")
        if res.get("online") and day is not None and self.on_event:
            self._fire(key, "daynum", day)   # 季節の判定に使う
        if res.get("online") and day is not None:
            old = (prev or {}).get("day")
            if old is not None and day != old:
                # 起点は「前に Day が変わった時刻」だけ。見張りを始めた時刻を
                # 起点にすると、1日ぶんに満たない時間を1日と誤って測ってしまう。
                self._fire(key, "day", (old, day, self._day_at.get(key)))
                self._day_at[key] = now

        self._last_seen[key] = now
        self.state[key] = res

    def _fire(self, key, kind, value):
        try:
            self.on_event(key, kind, value)
        except Exception:
            pass
