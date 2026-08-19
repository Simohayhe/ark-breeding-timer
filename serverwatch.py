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


class Watcher(threading.Thread):
    """登録されたサーバーを順に見て、状態を覚えておくスレッド。

    get_targets() は [(キー, "IP:ポート"), ...] を返す関数。
    生死やDayの変化は on_event(キー, 種類, 値) で知らせる。
      種類 "down" … 落ちた（値は最後に生きているのを見た時刻）
      種類 "up"   … 戻った（値はその時刻）
      種類 "day"  … Dayが増えた（値は (前のDay, 新しいDay, 前回増えた時刻)）
    """

    def __init__(self, get_targets, on_event=None, interval=60.0):
        super().__init__(daemon=True)
        self.get_targets = get_targets
        self.on_event = on_event
        self.interval = float(interval)
        self._halt = threading.Event()
        self._wake = threading.Event()   # 「いま見に行く」で叩く
        self.client = eos.Client()
        self.state = {}        # キー -> 最後に見た結果
        self._last_seen = {}   # キー -> 最後に確認した時刻
        self._day_at = {}      # キー -> そのDayになった時刻
        self._online_at = {}   # キー -> 最後に「起きている」のを見た時刻

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

    # ---- 見張る ----
    def run(self):
        while not self._halt.is_set():
            for key, address in (self.get_targets() or []):
                if self._halt.is_set():
                    break
                self._check_one(key, address)
            self._wake.wait(max(20.0, self.interval))
            self._wake.clear()

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

        # Day が増えたら知らせる（前に増えた時刻も一緒に）
        day = res.get("day")
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
