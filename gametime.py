# -*- coding: utf-8 -*-
"""ARK のゲーム内時計。

ARK には「今の時刻を返す」RCONコマンドが無いので、
**ゲーム内のHUD（Hキー）で読んだ時刻を1回合わせて、あとは実時間から計算する**。

昼と夜で進む速さが違う（サーバー設定の DayTimeSpeedScale / NightTimeSpeedScale）ので、
1日を「昼の区間」と「夜の区間」に分けて別々の速さで進める。

  昼: 05:15 → 20:25 （ゲーム内15時間10分）を day_real 秒（実時間）で進む
  夜: 20:25 → 05:15 （ゲーム内 8時間50分）を night_real 秒（実時間）で進む

**昼夜は半分ずつではない**。ARKの昼は夜よりずっと長い（15h10m 対 8h50m）。
倍率1のときで昼41.5分・夜18.6分、合わせてちょうど実1時間になる。

速さは設定で直接入れてもいいし、時刻を2回合わせれば自動で測れる（calibrate）。
"""
from __future__ import annotations

import time

DAY_SECONDS = 24 * 3600          # ゲーム内の1日
DAY_START = 5 * 3600 + 15 * 60     # 05:15 夜明け
NIGHT_START = 20 * 3600 + 25 * 60  # 20:25 日暮れ
DAY_SPAN = NIGHT_START - DAY_START       # 昼のゲーム内秒（15時間10分）
NIGHT_SPAN = DAY_SECONDS - DAY_SPAN      # 夜のゲーム内秒（ 8時間50分）
# 倍率1のときの実時間。1ゲーム内時間が昼164秒・夜126秒で、合計ちょうど3600秒
DEFAULT_DAY_REAL = 2487.0
DEFAULT_NIGHT_REAL = 1113.0


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

    def __init__(self, sync_real=0.0, sync_game=0, day_real=DEFAULT_DAY_REAL,
                 night_real=DEFAULT_NIGHT_REAL, address="", restarts=None,
                 restart_minutes=3.0, restart_done=0.0, day_boundary=None,
                 total_measured=False):
        self.sync_real = float(sync_real)      # 合わせたときの実時刻(epoch)
        self.sync_game = int(sync_game)        # そのときのゲーム内秒
        self.day_real = max(1.0, float(day_real))      # 昼ぜんぶにかかる実秒
        self.night_real = max(1.0, float(night_real))  # 夜ぜんぶにかかる実秒
        self.address = address or ""   # 死活を見るサーバー（host:port）
        # 定期再起動（実時間の "HH:MM" の並び）と、そのとき止まる分数。
        # サーバーが落ちている間はゲーム内時間が進まないので、その分を差し引く。
        self.restarts = list(restarts or [])
        self.restart_minutes = float(restart_minutes or 0)
        self.restart_done = float(restart_done or 0)   # ここまでは補正済み
        # ARKの「Day N」が変わるゲーム内時刻。最初の1回で学習して、
        # 以降はそこを基準に自動で合わせ直す。
        self.day_boundary = day_boundary
        # Dayの変化から1日の合計を測れたか。測れていれば、合わせ直しのときに
        # 合計はいじらず「昼と夜の配分」だけを解く。
        self.total_measured = bool(total_measured)

    @property
    def synced(self):
        return self.sync_real > 0

    # ---- 区間の切り替え ----
    def _segment(self, game_sec):
        """(この区間の終わりのゲーム内秒, ゲーム内1秒あたりの実秒)"""
        g = int(game_sec) % DAY_SECONDS
        if DAY_START <= g < NIGHT_START:
            return NIGHT_START, self.day_real / DAY_SPAN
        end = DAY_START + DAY_SECONDS if g >= NIGHT_START else DAY_START
        return end, self.night_real / NIGHT_SPAN

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

    def on_day_changed(self, prev_at, now=None):
        """サーバーの「Day N」が変わったときに呼ぶ。

        prev_at は前に変わった時刻(epoch)。2回ぶん揃えば、その間隔が
        そのまま「ゲーム内1日にかかる実時間」なので、速さを測り直せる。
        さらに、日の変わり目はいつも同じゲーム内時刻なので、そこへ合わせ直す。
        戻り値は何をしたかの説明。
        """
        now = now if now is not None else time.time()
        if not prev_at:
            # 1回目は起点が無い。「見張りを始めてから」の時間は1日ではないので
            # 何も測らない。次の変化から本物の1日ぶんが測れる。
            return "日付が変わりました（次の変わり目で速さを測ります）"
        done = []
        # 1) 前回の変わり目からの実時間 = ゲーム内1日ぶん
        full = now - prev_at
        if full >= 300:                      # 5分未満は短すぎる（取りこぼし等）
            before = self.full_day_real()
            if before > 0 and 0.2 <= full / before <= 5.0:
                ratio = full / before
                self.day_real *= ratio
                self.night_real *= ratio
                self.total_measured = True
                done.append("速さを測り直しました（1日 %.1f分）" % (full / 60))
        # 2) 日の変わり目のゲーム内時刻を覚える／そこへ合わせ直す
        if self.day_boundary is None:
            # 合わせ直したのが前の変わり目より後（＝ズレが小さい）ときだけ覚える。
            # 速さが分かっていない状態で覚えると、まるで違う時刻を掴んでしまう。
            if self.synced and self.total_measured and self.sync_real >= prev_at:
                self.day_boundary = self.game_at(now)
                done.append("日の変わり目を %s と覚えました"
                            % fmt_game_time(self.day_boundary))
        else:
            self.sync(self.day_boundary, now)
            done.append("%s に合わせ直しました" % fmt_game_time(self.day_boundary))
        return "／".join(done)

    def forget_learned(self):
        """覚えた速さと変わり目を捨てて、測り直しからやり直す。"""
        self.day_boundary = None
        self.total_measured = False
        self.day_real = DEFAULT_DAY_REAL
        self.night_real = DEFAULT_NIGHT_REAL

    def set_total(self, seconds):
        """1日の長さ（昼＋夜）を決める。昼と夜の比はそのまま。

        Dayの変わり目から測れた合計を入れる所。比が分かっていない段階では
        既定の比（昼15h10m/夜8h50m ぶん）のままなので、そのあと②で
        どちらかを測れば正しい配分に直る。
        """
        seconds = float(seconds)
        if seconds <= 0:
            return False
        before = self.full_day_real()
        if before <= 0:
            self.day_real = seconds * (DEFAULT_DAY_REAL
                                       / (DEFAULT_DAY_REAL + DEFAULT_NIGHT_REAL))
            self.night_real = seconds - self.day_real
        else:
            k = seconds / before
            self.day_real *= k
            self.night_real *= k
        return True

    def apply_measured_phase(self, phase_real, night=False):
        """昼か夜のどちらかを実測した値から、両方を決める。

        1日の長さは分かっている前提なので、逆側はただの引き算で出る
        （昼＋夜＝1日）。測った側が1日ぶんを食い潰してしまう場合は
        1日の長さのほうが間違っているので、測った側だけ入れて知らせる。
        戻り値は (直せたか, 説明)。
        """
        phase_real = float(phase_real)
        if phase_real <= 0:
            return False, "まだ測れていません"
        total = self.full_day_real()
        other = total - phase_real
        name = "夜" if night else "昼"
        if total <= 0 or other < 60:
            if night:
                self.night_real = phase_real
            else:
                self.day_real = phase_real
            return True, ("%s を %.1f分にしました。ただし1日の長さ(%.1f分)と"
                          "つじつまが合わないので、逆側は逆算していません。"
                          "①を測り直してください"
                          % (name, phase_real / 60, total / 60))
        if night:
            self.night_real, self.day_real = phase_real, other
        else:
            self.day_real, self.night_real = phase_real, other
        self.total_measured = True
        return True, ("✅ 昼 %.1f分 ／ 夜 %.1f分 にしました"
                      "（%sを実測して、1日 %.1f分の残りから逆算）"
                      % (self.day_real / 60, self.night_real / 60,
                         name, total / 60))

    def solve_split(self, prev_game, prev_real, new_game, new_real):
        """2回の同期から、昼と夜の配分を割り出す。

        1日の合計(day_real + night_real)は Day の変化から分かっているので、
        あとは「1回目から2回目までの実時間」を式にすれば連立方程式で解ける。

            昼D + 夜N = 合計T                     … Dayの変化から
            a×D + b×N = 実際にかかった時間        … a,b は昼夜をまたいだ割合

        1回目と2回目が同じ側（両方とも昼、など）だと a と b の差が小さく
        解が暴れるので、そのときは何もしない。戻り値は説明かNone。
        """
        total = self.full_day_real()
        elapsed = new_real - prev_real
        if total <= 0 or elapsed < 60 or elapsed > total * 1.2:
            return None                      # 間が短すぎ/1日以上あいている
        gd, gn = crossed(prev_game, new_game)
        a, b = gd / float(DAY_SPAN), gn / float(NIGHT_SPAN)
        if abs(a - b) < 0.15:
            return None                      # 昼夜の割合が近すぎて分けられない
        day = (elapsed - b * total) / (a - b)
        if not (0.05 * total <= day <= 0.95 * total):
            return None                      # ありえない値
        self.day_real = day
        self.night_real = total - day
        return ("昼と夜の配分が分かりました（昼 %.1f分 / 夜 %.1f分）"
                % (self.day_real / 60, self.night_real / 60))

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
                "restart_done": self.restart_done,
                "day_boundary": self.day_boundary,
                "total_measured": self.total_measured,
                "model": 2}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        day = float(d.get("day_real", DEFAULT_DAY_REAL))
        night = float(d.get("night_real", DEFAULT_NIGHT_REAL))
        if d.get("model") != 2 and day > 0 and night > 0:
            # v1.20.0 まで昼夜を12時間ずつだと思って持っていた値。区間の長さが
            # 変わったので、そのままでは意味が違う。1日の合計だけは Day の変化から
            # 測れた本物なので、それを保って既定の比で振り直す。
            total = day + night
            ratio = DEFAULT_DAY_REAL / (DEFAULT_DAY_REAL + DEFAULT_NIGHT_REAL)
            day, night = total * ratio, total * (1 - ratio)
        return cls(d.get("sync_real", 0.0), d.get("sync_game", 0),
                   day, night,
                   d.get("address", ""), d.get("restarts"),
                   d.get("restart_minutes", 3.0), d.get("restart_done", 0.0),
                   d.get("day_boundary"), d.get("total_measured", False))


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

    def phase_real(self, night=False):
        """この速さのまま進んだとして、昼（または夜）ぜんぶにかかる実秒。"""
        p = self.per_game_minute()
        if p is None:
            return None
        return p * ((NIGHT_SPAN if night else DAY_SPAN) / 60.0)


def crossed(g0, g1):
    """ゲーム内 g0 から g1 まで進むあいだの「昼」「夜」の秒数を返す。

    前へ進む向きだけを見る（1日ぶんで折り返す）。昼と夜で速さが違うので、
    実時間に直すにはこの内訳が要る。
    """
    g0 = int(g0) % DAY_SECONDS
    g1 = int(g1) % DAY_SECONDS
    total = (g1 - g0) % DAY_SECONDS
    day_sec = night_sec = 0
    g = g0
    left = total
    guard = 0
    while left > 0 and guard < 10:
        guard += 1
        if DAY_START <= g < NIGHT_START:
            end, is_day = NIGHT_START, True
        else:
            end, is_day = (DAY_START + DAY_SECONDS if g >= NIGHT_START
                           else DAY_START), False
        span = min(left, (end - g) if end > g else (end + DAY_SECONDS - g))
        if is_day:
            day_sec += span
        else:
            night_sec += span
        left -= span
        g = (g + span) % DAY_SECONDS
    return day_sec, night_sec
