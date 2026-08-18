# -*- coding: utf-8 -*-
"""ARK のゲーム内時計。

ARK には「今の時刻を返す」RCONコマンドが無いので、
**ゲーム内のHUD（Hキー）で読んだ時刻を1回合わせて、あとは実時間から計算する**。

昼と夜で進む速さが違う（サーバー設定の DayTimeSpeedScale / NightTimeSpeedScale）ので、
1日を「昼の区間」と「夜の区間」に分けて別々の速さで進める。

  昼: 05:30 → 17:30 （ゲーム内12時間）を day_real 秒（実時間）で進む
  夜: 17:30 → 05:30 （ゲーム内12時間）を night_real 秒（実時間）で進む

速さは設定で直接入れてもいいし、時刻を2回合わせれば自動で測れる（calibrate）。
"""
from __future__ import annotations

import time

DAY_SECONDS = 24 * 3600          # ゲーム内の1日
DAY_START = 5 * 3600 + 30 * 60   # 05:30 夜明け
NIGHT_START = 17 * 3600 + 30 * 60  # 17:30 日暮れ


def parse_game_time(text):
    """'17:30' / '17:30:00' / '1730' をゲーム内秒（0〜86399）に。"""
    t = (text or "").strip()
    if not t:
        return None
    if ":" not in t and t.isdigit() and len(t) in (3, 4):
        t = t[:-2] + ":" + t[-2:]
    parts = t.split(":")
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return None
    if not 2 <= len(nums) <= 3:
        return None
    h, m = nums[0], nums[1]
    s = nums[2] if len(nums) == 3 else 0
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        return None
    return h * 3600 + m * 60 + s


def fmt_game_time(sec):
    sec = int(sec) % DAY_SECONDS
    return "%02d:%02d" % (sec // 3600, (sec % 3600) // 60)


def is_night(game_sec):
    g = int(game_sec) % DAY_SECONDS
    return g >= NIGHT_START or g < DAY_START


class GameClock:
    """合わせた時刻から、いまのゲーム内時刻を割り出す。"""

    def __init__(self, sync_real=0.0, sync_game=0, day_real=1500.0,
                 night_real=1500.0, address="", restarts=None,
                 restart_minutes=3.0, restart_done=0.0):
        self.sync_real = float(sync_real)      # 合わせたときの実時刻(epoch)
        self.sync_game = int(sync_game)        # そのときのゲーム内秒
        self.day_real = max(1.0, float(day_real))      # 昼12時間にかかる実秒
        self.night_real = max(1.0, float(night_real))  # 夜12時間にかかる実秒
        self.address = address or ""   # 死活を見るサーバー（host:port）
        # 定期再起動（実時間の "HH:MM" の並び）と、そのとき止まる分数。
        # サーバーが落ちている間はゲーム内時間が進まないので、その分を差し引く。
        self.restarts = list(restarts or [])
        self.restart_minutes = float(restart_minutes or 0)
        self.restart_done = float(restart_done or 0)   # ここまでは補正済み

    @property
    def synced(self):
        return self.sync_real > 0

    # ---- 区間の切り替え ----
    def _segment(self, game_sec):
        """(この区間の終わりのゲーム内秒, ゲーム内1秒あたりの実秒)"""
        g = int(game_sec) % DAY_SECONDS
        half = 12 * 3600
        if DAY_START <= g < NIGHT_START:
            return NIGHT_START, self.day_real / half
        end = DAY_START + DAY_SECONDS if g >= NIGHT_START else DAY_START
        return end, self.night_real / half

    def game_at(self, real_now=None):
        """いまのゲーム内秒。"""
        if not self.synced:
            return None
        left = max(0.0, (real_now if real_now is not None else time.time())
                   - self.sync_real)
        g = float(self.sync_game)
        # 区間ごとに進める（1日ぶんで打ち切って、余りは丸ごと足す）
        guard = 0
        while left > 0 and guard < 2000:
            guard += 1
            end, rate = self._segment(g)
            need = end - g if end > g else end + DAY_SECONDS - g
            cost = need * rate
            if cost > left:
                g += left / rate
                left = 0
            else:
                g = end
                left -= cost
        return int(g) % DAY_SECONDS

    def real_until(self, target_game, real_now=None):
        """いまから、そのゲーム内時刻になるまでの実秒。"""
        now_game = self.game_at(real_now)
        if now_game is None:
            return None
        target = int(target_game) % DAY_SECONDS
        g = float(now_game)
        total = 0.0
        guard = 0
        while guard < 2000:
            guard += 1
            end, rate = self._segment(g)
            span = end - g if end > g else end + DAY_SECONDS - g
            # この区間の中に目標があるか
            to_target = (target - g) % DAY_SECONDS
            if 0 < to_target <= span:
                return total + to_target * rate
            if to_target == 0:
                return total
            total += span * rate
            g = end % DAY_SECONDS if end >= DAY_SECONDS else end
        return None

    def next_night(self, real_now=None):
        return self.real_until(NIGHT_START, real_now)

    def next_day(self, real_now=None):
        return self.real_until(DAY_START, real_now)

    # ---- 合わせる・測る ----
    def hold(self, seconds):
        """その秒数ぶん、時計を止める。

        サーバーが落ちている間はゲーム内時間が進まないので、
        合わせた基準時刻を後ろにずらして「無かったこと」にする。
        """
        if self.synced and seconds > 0:
            self.sync_real += float(seconds)

    def sync(self, game_sec, real_now=None):
        self.sync_real = real_now if real_now is not None else time.time()
        self.sync_game = int(game_sec) % DAY_SECONDS
        # 合わせ直した時点より前の再起動を後から引かないようにする
        self.restart_done = self.sync_real

    def calibrate(self, game_sec, real_now=None):
        """2回目以降の同期。ズレから速さを測り直す。

        直前の同期からいままでに進んだ「ゲーム内の時間」と「実時間」を比べて、
        昼と夜の速さを同じ割合で伸び縮みさせる。
        戻り値: (成功したか, 説明)
        """
        now = real_now if real_now is not None else time.time()
        if not self.synced:
            self.sync(game_sec, now)
            return False, "1回目なので、いまの時刻を覚えました"
        real_elapsed = now - self.sync_real
        if real_elapsed < 60:
            self.sync(game_sec, now)
            return False, "間が短すぎて測れないので、時刻だけ合わせました（1分以上あけて再度）"

        actual = (int(game_sec) - self.sync_game) % DAY_SECONDS
        if actual <= 0:
            self.sync(game_sec, now)
            return False, "ゲーム内時刻が進んでいないので、時刻だけ合わせました"

        # いまの設定だと、その実時間で何秒進むはずだったか
        expected = self._advance(self.sync_game, real_elapsed)
        if expected <= 0:
            self.sync(game_sec, now)
            return False, "うまく測れなかったので、時刻だけ合わせました"

        ratio = expected / actual      # 進みすぎていたら >1 → 遅くする
        ratio = max(0.2, min(5.0, ratio))
        self.day_real *= ratio
        self.night_real *= ratio
        self.sync(game_sec, now)
        return True, "速さを測り直しました（1日 %.0f分）" % (self.full_day_real() / 60)

    def _advance(self, from_game, real_seconds):
        """from_game から real_seconds 進めたときの「進んだゲーム内秒」。"""
        g = float(from_game)
        left = float(real_seconds)
        moved = 0.0
        guard = 0
        while left > 0 and guard < 2000:
            guard += 1
            end, rate = self._segment(g)
            span = end - g if end > g else end + DAY_SECONDS - g
            cost = span * rate
            if cost > left:
                moved += left / rate
                left = 0
            else:
                moved += span
                left -= cost
                g = end % DAY_SECONDS
        return moved

    def apply_restarts(self, now=None):
        """過ぎた定期再起動のぶんだけ、時計を止める。止めた回数を返す。"""
        if not self.synced or not self.restarts or self.restart_minutes <= 0:
            return 0
        now = now if now is not None else time.time()
        if self.restart_done <= 0:
            self.restart_done = now      # 初回は過去にさかのぼらない
            return 0
        applied = 0
        for occ in _restart_occurrences(self.restarts, now):
            if self.restart_done < occ <= now:
                self.hold(self.restart_minutes * 60)
                self.restart_done = occ
                applied += 1
        return applied

    def full_day_real(self):
        return self.day_real + self.night_real

    def to_dict(self):
        return {"sync_real": self.sync_real, "sync_game": self.sync_game,
                "day_real": self.day_real, "night_real": self.night_real,
                "address": self.address, "restarts": self.restarts,
                "restart_minutes": self.restart_minutes,
                "restart_done": self.restart_done}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(d.get("sync_real", 0.0), d.get("sync_game", 0),
                   d.get("day_real", 1500.0), d.get("night_real", 1500.0),
                   d.get("address", ""), d.get("restarts"),
                   d.get("restart_minutes", 3.0), d.get("restart_done", 0.0))


class ClockSet:
    """マップごとの時計をまとめて持つ。

    サーバーごとに昼夜の長さも進み具合も違うので、マップ単位で別々に覚える。
    """

    def __init__(self, data=None):
        self.clocks = {}
        self.order = []
        self.current = ""
        for item in (data or {}).get("maps") or []:
            name = (item.get("name") or "").strip()
            if not name or name in self.clocks:
                continue
            self.clocks[name] = GameClock.from_dict(item)
            self.order.append(name)
        self.current = (data or {}).get("current") or ""
        if self.current not in self.clocks:
            self.current = self.order[0] if self.order else ""

    def add(self, name):
        name = (name or "").strip()
        if not name or name in self.clocks:
            return False
        self.clocks[name] = GameClock()
        self.order.append(name)
        self.current = name
        return True

    def remove(self, name):
        if name not in self.clocks:
            return False
        del self.clocks[name]
        self.order.remove(name)
        if self.current == name:
            self.current = self.order[0] if self.order else ""
        return True

    def rename(self, old, new):
        new = (new or "").strip()
        if old not in self.clocks or not new or new in self.clocks:
            return False
        self.clocks[new] = self.clocks.pop(old)
        self.order[self.order.index(old)] = new
        if self.current == old:
            self.current = new
        return True

    def get(self, name=None):
        return self.clocks.get(name or self.current)

    def to_dict(self):
        maps = []
        for n in self.order:
            d = self.clocks[n].to_dict()
            d["name"] = n
            maps.append(d)
        return {"maps": maps, "current": self.current}

    @classmethod
    def migrate(cls, old_single, data=None):
        """昔の「1つだけの時計」設定から引き継ぐ。"""
        cs = cls(data)
        if not cs.order and old_single and old_single.get("sync_real"):
            cs.clocks["マップ1"] = GameClock.from_dict(old_single)
            cs.order.append("マップ1")
            cs.current = "マップ1"
        return cs


def _restart_occurrences(times, now, back_days=2):
    """"HH:MM" の並びから、直近 back_days 日ぶんの実時刻(epoch)を古い順に返す。"""
    # 秒未満を残すと、呼ぶたびに候補の時刻が微妙にズレて
    # 同じ再起動を何度も引いてしまう。整数秒に丸めておく。
    now = int(now)
    lt = time.localtime(now)
    midnight = now - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)
    out = []
    for t in times:
        sec = parse_game_time(t)     # "HH:MM" を秒に（実時刻にもそのまま使える）
        if sec is None:
            continue
        for day in range(-back_days, 1):
            out.append(midnight + day * DAY_SECONDS + sec)
    return sorted(out)


class TapMeter:
    """ゲーム内時計の進む速さを、押した間隔から実測する。

    使いかた: ゲーム内の時刻表示を見ながら、分が変わるたびに tap() を呼ぶ。
    数回ぶん貯まれば「ゲーム内1分あたり実何秒か」が出る。

    step は「何ゲーム内分ごとに押すか」。1分ごとが押しやすいが、
    10分ごとにすればもっと正確になる。
    """

    def __init__(self, step=1):
        self.step = max(1, int(step))
        self.taps = []

    def tap(self, now=None):
        self.taps.append(now if now is not None else time.time())
        return len(self.taps)

    def reset(self):
        self.taps = []

    @property
    def intervals(self):
        return [b - a for a, b in zip(self.taps, self.taps[1:])]

    @property
    def count(self):
        """使える間隔の数（押した回数 - 1）。"""
        return max(0, len(self.taps) - 1)

    def per_game_minute(self):
        """ゲーム内1分あたりの実秒。まだ測れないなら None。

        押し間違いの影響を減らすため、3つ以上あるときは中央値を使う。
        """
        iv = self.intervals
        if not iv:
            return None
        iv = sorted(iv)
        n = len(iv)
        mid = iv[n // 2] if n % 2 else (iv[n // 2 - 1] + iv[n // 2]) / 2
        return mid / self.step

    def spread(self):
        """間隔のばらつき（最大と最小の差、秒）。押し方の安定を見る目安。"""
        iv = self.intervals
        return (max(iv) - min(iv)) if len(iv) >= 2 else None

    def half_day_real(self):
        """この速さでの「ゲーム内12時間」にかかる実秒。"""
        p = self.per_game_minute()
        return None if p is None else p * 720      # 12時間 = 720ゲーム内分
