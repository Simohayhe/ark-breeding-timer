# -*- coding: utf-8 -*-
"""ARK Breeding Timer — かわいいカウントダウンタイマー

・自由タイマー: ◯時間◯分◯秒後 / 指定時刻 / 繰り返し
・ARKブリーディング: 種族を選ぶとサーバー倍率から
  孵化・妊娠・成長・刷り込み・再交配CD を自動計算
・音は内蔵7種＋自分のmp3、音量調整つき

    python ark_breeding_timer.py

設定と実行中タイマー: %APPDATA%\\ArkBreedingTimer\\
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import sounds as snd
import theme as th

APP_NAME = "ARK Breeding Timer"


def _res_dir():
    """同梱ファイルの置き場（PyInstallerでexe化したときは展開先）"""
    base = getattr(sys, "_MEIPASS", None)
    return base or os.path.dirname(os.path.abspath(__file__))


HERE = _res_dir()
DATA_DIR = os.path.join(HERE, "data")
STATE_DIR = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), "ArkBreedingTimer")
CONFIG_PATH = os.path.join(STATE_DIR, "config.json")
TIMERS_PATH = os.path.join(STATE_DIR, "timers.json")
SOUND_CACHE = os.path.join(STATE_DIR, "sounds")

BASE_CUDDLE_INTERVAL = 28800.0  # ARK の刷り込み基準間隔 = 8時間

DEFAULT_CONFIG = {
    # ARKサーバー倍率（既定値はこのホストの dynconfig に合わせてある）
    "egg_hatch_speed": 15.0,
    "baby_mature_speed": 185.0,
    "cuddle_interval_mult": 0.03125,
    "mating_interval_mult": 0.001,
    "imprint_amount_mult": 1.0,
    "gestation_uses_hatch_mult": True,
    # 音
    "volume": 0.7,
    "sound_done": snd.DEFAULT_DONE,
    "sound_prewarn": snd.DEFAULT_PREWARN,
    "my_sounds": [],          # 自分で選んだファイルの履歴
    # 通知
    "sound": True,
    "popup": True,
    "toast": True,
    "repeat_alarm": True,
    "prewarn_sec": 60,
    "auto_chain": True,
    # 画面
    "always_on_top": True,
    "geometry": "980x700",
}


# ---------------------------------------------------------------- 小道具
def fmt_dur(sec: float) -> str:
    neg = sec < 0
    sec = abs(int(round(sec)))
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        out = "%d日 %d:%02d:%02d" % (d, h, m, s)
    elif h:
        out = "%d:%02d:%02d" % (h, m, s)
    else:
        out = "%d:%02d" % (m, s)
    return ("-" + out) if neg else out


def fmt_eta(ts: float) -> str:
    dt = datetime.fromtimestamp(ts)
    if dt.date() == datetime.now().date():
        return dt.strftime("%H:%M")
    return dt.strftime("%m/%d %H:%M")


def parse_duration(text: str):
    """'1:23:45' / '12:30' / '90m' / '1h30m' / '45'(=分) を秒に。"""
    t = (text or "").strip().lower().replace(" ", "")
    if not t:
        return None
    if ":" in t:
        try:
            nums = [float(p) for p in t.split(":")]
        except ValueError:
            return None
        if len(nums) == 3:
            return nums[0] * 3600 + nums[1] * 60 + nums[2]
        if len(nums) == 2:
            return nums[0] * 60 + nums[1]
        return None
    total, num, matched = 0.0, "", False
    for ch in t:
        if ch.isdigit() or ch == ".":
            num += ch
        elif ch in "dhms":
            if not num:
                return None
            total += float(num) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[ch]
            num, matched = "", True
        else:
            return None
    if num:
        total += float(num) * (1 if matched else 60)  # 単位なしは「分」
    return total


def parse_clock(text: str):
    """'21:30' / '8/5 21:30' / '25:00'(=翌1時) を絶対時刻(epoch)に。"""
    t = (text or "").strip()
    if not t:
        return None
    now = datetime.now()
    date_part, _, time_part = t.rpartition(" ")
    try:
        bits = [int(x) for x in time_part.strip().split(":")]
    except ValueError:
        return None
    if not 2 <= len(bits) <= 3:
        return None
    hh, mm = bits[0], bits[1]
    ss = bits[2] if len(bits) == 3 else 0
    if not (0 <= hh <= 47 and 0 <= mm < 60 and 0 <= ss < 60):
        return None
    day_shift = 0
    if hh >= 24:
        day_shift, hh = divmod(hh, 24)
    y, mo, d = now.year, now.month, now.day
    date_part = date_part.strip()
    if date_part:
        sep = "-" if "-" in date_part else "/"
        try:
            nums = [int(x) for x in date_part.split(sep) if x]
        except ValueError:
            return None
        if len(nums) == 3:
            y, mo, d = nums
        elif len(nums) == 2:
            mo, d = nums
        else:
            return None
    try:
        ts = datetime(y, mo, d, hh, mm, ss).timestamp() + day_shift * 86400
    except ValueError:
        return None
    if not date_part and ts <= time.time():
        ts += 86400  # 今日はもう過ぎている -> 明日
    return ts


def load_json(path, default):
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------- 種族データ
class SpeciesDB:
    def __init__(self, path):
        data = load_json(path, {"species": []})
        self.source = data.get("source", {})
        self.species = data.get("species", [])
        self.by_name = {s["name"]: s for s in self.species}

    def search(self, q):
        q = (q or "").strip().lower()
        if not q:
            return self.species
        hits, subs = [], []
        for s in self.species:
            name = s["name"].lower()
            jp = s.get("jp", "")
            if name.startswith(q) or jp.startswith(q):
                hits.append(s)
            elif q in name or q in jp:
                subs.append(s)
        return hits + subs


def calc_times(sp: dict, cfg: dict) -> dict:
    hatch_mult = max(cfg["egg_hatch_speed"], 1e-9)
    mature_mult = max(cfg["baby_mature_speed"], 1e-9)
    hatch = (sp.get("incubation") or 0) / hatch_mult
    gest = (sp.get("gestation") or 0) / (
        hatch_mult if cfg.get("gestation_uses_hatch_mult", True) else 1.0)
    mature = (sp.get("maturation") or 0) / mature_mult
    interval = BASE_CUDDLE_INTERVAL * cfg["cuddle_interval_mult"]
    if mature > 0 and interval > 0:
        n = max(1, int(mature // interval))
        per = min(100.0, (interval / mature) * 100.0 * cfg.get("imprint_amount_mult", 1.0))
        if per * n > 100.0:
            per = 100.0 / n
    else:
        n, per = 0, 0.0
    return {
        "hatch": hatch,
        "gestation": gest,
        "mature": mature,
        "imprint_interval": interval,
        "imprint_count": n,
        "imprint_per": per,
        "juvenile": mature * 0.10,
        "cd_lo": (sp.get("cd_min") or 0) * cfg["mating_interval_mult"],
        "cd_hi": (sp.get("cd_max") or 0) * cfg["mating_interval_mult"],
    }


# ---------------------------------------------------------------- タイマー
class BreedTimer:
    """1本のカウントダウン。end_ts(絶対時刻)で持つのでアプリを閉じても続く。"""

    def __init__(self, kind, label, total, species="", **kw):
        self.id = kw.get("id") or uuid.uuid4().hex[:8]
        self.kind = kind
        self.label = label
        self.species = species
        self.total = float(total)
        self.end_ts = kw.get("end_ts") or (time.time() + self.total)
        self.paused = kw.get("paused", False)
        self.pause_left = kw.get("pause_left", 0.0)
        self.done = kw.get("done", False)
        self.prewarned = kw.get("prewarned", False)
        self.milestone_done = kw.get("milestone_done", False)
        self.milestone_frac = kw.get("milestone_frac")
        self.milestone_text = kw.get("milestone_text", "")
        self.imp_index = kw.get("imp_index", 0)
        self.imp_count = kw.get("imp_count", 0)
        self.imp_per = kw.get("imp_per", 0.0)
        self.mature_end = kw.get("mature_end")
        self.chain = kw.get("chain")
        self.repeat = kw.get("repeat", False)
        self.sound = kw.get("sound", "")   # "" なら既定音
        self.note = kw.get("note", "")

    def remaining(self, now=None):
        if self.paused:
            return self.pause_left
        return self.end_ts - (now if now is not None else time.time())

    def progress(self, now=None):
        if self.total <= 0:
            return 1.0
        return min(1.0, max(0.0, 1.0 - self.remaining(now) / self.total))

    @property
    def milestone_ts(self):
        if self.milestone_frac is None:
            return None
        return self.end_ts - self.total * (1.0 - self.milestone_frac)

    def toggle_pause(self):
        if self.paused:
            self.end_ts = time.time() + self.pause_left
            self.paused = False
        else:
            self.pause_left = max(0.0, self.remaining())
            self.paused = True

    FIELDS = ("id", "kind", "label", "species", "total", "end_ts", "paused",
              "pause_left", "done", "prewarned", "milestone_done", "milestone_frac",
              "milestone_text", "imp_index", "imp_count", "imp_per", "mature_end",
              "chain", "repeat", "sound", "note")

    def to_dict(self):
        return {k: getattr(self, k) for k in self.FIELDS}

    @classmethod
    def from_dict(cls, d):
        return cls(d["kind"], d.get("label", ""), d.get("total", 0),
                   species=d.get("species", ""),
                   **{k: v for k, v in d.items()
                      if k not in ("kind", "label", "total", "species")})


# ---------------------------------------------------------------- 通知
class Notifier:
    def __init__(self, app):
        self.app = app

    def fire(self, title, body, urgent=True, sound_spec=None):
        cfg = self.app.cfg
        if cfg.get("sound"):
            spec = sound_spec or (cfg["sound_done"] if urgent else cfg["sound_prewarn"])
            snd.play_async(spec, cfg.get("volume", 0.7), SOUND_CACHE)
        if cfg.get("toast"):
            threading.Thread(target=self._toast, args=(title, body), daemon=True).start()
        if cfg.get("popup"):
            self.app.show_popup(title, body, urgent, sound_spec)
        self.app.flash_taskbar()

    def _toast(self, title, body):
        app_id = ("{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell"
                  "\\v1.0\\powershell.exe")
        ps = (
            "$ErrorActionPreference='Stop';"
            "$null=[Windows.UI.Notifications.ToastNotificationManager,"
            "Windows.UI.Notifications,ContentType=WindowsRuntime];"
            "$null=[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom,"
            "ContentType=WindowsRuntime];"
            "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            "$n=$t.GetElementsByTagName('text');"
            "$null=$n.Item(0).AppendChild($t.CreateTextNode(%s));"
            "$null=$n.Item(1).AppendChild($t.CreateTextNode(%s));"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier(%s)"
            ".Show([Windows.UI.Notifications.ToastNotification]::new($t));"
        ) % (_ps(title), _ps(body or " "), _ps(app_id))
        try:
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass


def _ps(s):
    return "'" + str(s).replace("'", "''") + "'"


# ---------------------------------------------------------------- 本体
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = dict(DEFAULT_CONFIG)
        self.cfg.update(load_json(CONFIG_PATH, {}))
        self.db = SpeciesDB(os.path.join(DATA_DIR, "species.json"))
        self.notifier = Notifier(self)
        self.timers: list[BreedTimer] = []
        self.cards: dict[str, TimerCard] = {}
        self.popup = None
        self.alarm_on = False

        self.title(APP_NAME)
        self.geometry(self.cfg.get("geometry", "980x700"))
        self.minsize(660, 420)
        self.configure(bg=th.BG)
        self.F = th.init(self)
        try:
            self._icon = th.make_icon(48)
            self.iconphoto(True, self._icon)
        except Exception:
            pass
        threading.Thread(target=snd.prebuild, args=(SOUND_CACHE,), daemon=True).start()

        self._build_ui()
        self._load_timers()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.attributes("-topmost", bool(self.cfg["always_on_top"]))
        self.after(200, self._tick)

    # ---------------- 画面 ----------------
    def _build_ui(self):
        F = self.F
        head = tk.Frame(self, bg=th.BG)
        head.pack(fill="x", padx=18, pady=(14, 0))

        top = tk.Frame(head, bg=th.BG)
        top.pack(fill="x")
        tk.Label(top, text="⏰ ふわふわタイマー", bg=th.BG, fg=th.INK,
                 font=F["head"]).pack(side="left")
        th.RoundButton(top, "⚙ 設定", self.open_settings, kind="soft",
                       bg=th.BG, font=F["small"]).pack(side="right", padx=(6, 0))
        th.RoundButton(top, "🔔 音を試す", self.test_sound, kind="soft",
                       bg=th.BG, font=F["small"]).pack(side="right", padx=6)
        self.var_top = tk.BooleanVar(value=bool(self.cfg["always_on_top"]))
        tk.Checkbutton(top, text="最前面", variable=self.var_top,
                       command=self.apply_topmost, bg=th.BG, fg=th.INK_SUB,
                       activebackground=th.BG, activeforeground=th.INK,
                       selectcolor=th.CARD, font=F["small"], bd=0,
                       highlightthickness=0).pack(side="right", padx=6)

        self.lbl_next = tk.Label(head, text="", bg=th.BG, fg=th.INK_SUB,
                                 font=F["cute"], anchor="w")
        self.lbl_next.pack(fill="x", pady=(2, 10))

        quick = tk.Frame(head, bg=th.BG)
        quick.pack(fill="x", pady=(0, 10))
        th.RoundButton(quick, "＋ 新しいタイマー", self.open_new_dialog,
                       kind="primary", bg=th.BG, font=F["cute"]).pack(side="left")
        tk.Label(quick, text="  さくっと: ", bg=th.BG, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")
        for text, sec in (("1分", 60), ("3分", 180), ("5分", 300), ("10分", 600),
                          ("15分", 900), ("30分", 1800), ("1時間", 3600)):
            th.Chip(quick, text, lambda s=sec, t=text: self.quick_add(t, s),
                    bg=th.BG, font=F["small"]).pack(side="left", padx=3)

        # 一覧
        wrap = tk.Frame(self, bg=th.BG)
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.canvas = tk.Canvas(wrap, bg=th.BG, highlightthickness=0, bd=0)
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview,
                           style="Cute.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.list_frame = tk.Frame(self.canvas, bg=th.BG)
        self._win = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.list_frame.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win, width=e.width))
        self.bind_all("<MouseWheel>", self._on_wheel)

        self.empty = tk.Frame(self.list_frame, bg=th.BG)
        tk.Label(self.empty, text="🍼", bg=th.BG, font=(th.JP, 38)).pack(pady=(40, 6))
        tk.Label(self.empty, text="まだタイマーはありません", bg=th.BG, fg=th.INK,
                 font=F["cute_b"]).pack()
        tk.Label(self.empty, text="上の「さくっと」を押すか、"
                                 "「＋ 新しいタイマー」から作れます",
                 bg=th.BG, fg=th.INK_SUB, font=F["small"]).pack(pady=(4, 0))

    def _on_wheel(self, e):
        try:
            self.canvas.yview_scroll(int(-e.delta / 120), "units")
        except tk.TclError:
            pass

    # ---------------- タイマー ----------------
    def quick_add(self, label, sec):
        self.add_timer(BreedTimer("custom", label + "タイマー", sec))

    def add_timer(self, t: BreedTimer):
        self.timers.append(t)
        self.rebuild_list()
        self.save_timers()

    def remove_timer(self, tid):
        self.timers = [t for t in self.timers if t.id != tid]
        self.rebuild_list()
        self.save_timers()

    def clear_done(self):
        self.timers = [t for t in self.timers if not (t.done and t.remaining() <= 0)]
        self.rebuild_list()
        self.save_timers()

    def rebuild_list(self):
        for c in self.cards.values():
            c.destroy()
        self.cards.clear()
        self.empty.pack_forget()
        if not self.timers:
            self.empty.pack(fill="x")
            return
        for t in sorted(self.timers, key=lambda x: (x.remaining() <= 0, x.remaining())):
            card = TimerCard(self.list_frame, self, t)
            card.pack(fill="x", pady=1)
            self.cards[t.id] = card

    def save_timers(self):
        save_json(TIMERS_PATH, [t.to_dict() for t in self.timers])

    def _load_timers(self):
        for d in load_json(TIMERS_PATH, []):
            try:
                self.timers.append(BreedTimer.from_dict(d))
            except Exception:
                pass
        expired = [t for t in self.timers if not t.done and t.remaining() <= 0]
        for t in expired:
            t.done = True
        self.rebuild_list()
        if expired:
            names = "、".join(t.label for t in expired[:5])
            self.after(700, lambda: self.notifier.fire(
                "起動前に終わっていたタイマー", names, urgent=False))

    def _tick(self):
        now = time.time()
        changed = False
        for t in list(self.timers):
            if t.paused:
                continue
            rem = t.remaining(now)
            pre = float(self.cfg.get("prewarn_sec") or 0)
            if pre > 0 and not t.prewarned and not t.done and 0 < rem <= pre:
                t.prewarned = True
                changed = True
                self.notifier.fire("もうすぐ: %s" % t.label,
                                   "あと %s" % fmt_dur(rem), urgent=False)
            ms = t.milestone_ts
            if ms is not None and not t.milestone_done and now >= ms:
                t.milestone_done = True
                changed = True
                self.notifier.fire("%s — %s" % (t.label, t.milestone_text),
                                   t.species, urgent=False)
            if rem <= 0 and not t.done:
                t.done = True
                changed = True
                self._on_complete(t)
        if changed:
            self.save_timers()
            self.rebuild_list()
        for c in self.cards.values():
            c.update_view(now)
        self._update_head(now)
        self.after(250, self._tick)

    def _on_complete(self, t: BreedTimer):
        if t.kind == "imprint":
            self.notifier.fire(
                "💗 刷り込みの時間! — %s" % t.label,
                "%s  %d/%d回目 (+%.1f%%)" % (t.species, t.imp_index + 1,
                                             t.imp_count, t.imp_per),
                sound_spec=t.sound or None)
            return
        msg = {"hatch": "🥚 卵が孵りました", "gestation": "🌸 出産の時間です",
               "mature": "🌱 成長が完了しました", "matingcd": "💞 再交配できます",
               "custom": "⏰ 時間になりました"}.get(t.kind, "時間になりました")
        self.notifier.fire("%s — %s" % (msg, t.label), t.species or t.note or "",
                           sound_spec=t.sound or None)
        if t.chain and self.cfg.get("auto_chain"):
            self._spawn_chain(t)
        if t.repeat and t.total > 0:
            t.end_ts = time.time() + t.total
            t.done = False
            t.prewarned = False

    def _spawn_chain(self, t: BreedTimer):
        sp = self.db.by_name.get(t.species)
        if not sp:
            return
        c = calc_times(sp, self.cfg)
        for m in self.make_timers(sp, t.label, c, ("mature", "imprint")):
            self.timers.append(m)
        self.rebuild_list()
        self.save_timers()

    def make_timers(self, sp, label, c, kinds, offset=0.0):
        """種族と計算結果からタイマー群を作る。offset秒だけ経過済みとして扱う。"""
        out, now = [], time.time()
        for kind, total in (("hatch", c["hatch"]), ("gestation", c["gestation"])):
            if kind in kinds and total > 0:
                t = BreedTimer(kind, label, total, sp["name"])
                t.end_ts = now + max(0.0, total - offset)
                t.chain = True
                out.append(t)
        if "mature" in kinds and c["mature"] > 0:
            t = BreedTimer("mature", label, c["mature"], sp["name"])
            t.end_ts = now + max(0.0, c["mature"] - offset)
            t.milestone_text = "成長10% おいていけます"
            if offset < c["mature"] * 0.10:
                t.milestone_frac = 0.10
            else:
                t.milestone_done = True
            out.append(t)
        if "imprint" in kinds and c["imprint_count"] > 0:
            t = BreedTimer("imprint", label, c["imprint_interval"], sp["name"])
            t.end_ts = now + max(0.0, c["imprint_interval"] - offset)
            t.imp_count = c["imprint_count"]
            t.imp_per = c["imprint_per"]
            t.mature_end = now + max(0.0, c["mature"] - offset)
            out.append(t)
        if "matingcd" in kinds and c["cd_hi"] > 0:
            t = BreedTimer("matingcd", label, c["cd_lo"], sp["name"])
            t.end_ts = now + max(0.0, c["cd_lo"] - offset)
            t.note = "最短 %s / 最長 %s のあいだでランダム" % (
                fmt_dur(c["cd_lo"]), fmt_dur(c["cd_hi"]))
            out.append(t)
        return out

    def imprint_next(self, t: BreedTimer):
        t.imp_index += 1
        if t.imp_index >= t.imp_count:
            t.done = True
            t.end_ts = time.time()
            t.note = "刷り込み完了 %d/%d 🎉" % (t.imp_index, t.imp_count)
        else:
            t.done = False
            t.prewarned = False
            t.end_ts = time.time() + t.total
        self.rebuild_list()
        self.save_timers()

    def _update_head(self, now):
        live = [t for t in self.timers if not t.done and not t.paused]
        if not live:
            self.title(APP_NAME)
            self.lbl_next.config(text="のんびり待機中… ")
            return
        nxt = min(live, key=lambda t: t.remaining(now))
        rem = nxt.remaining(now)
        self.title("%s — %s" % (fmt_dur(rem), nxt.label))
        emoji = th.KIND_STYLE.get(nxt.kind, ("⏰",))[0]
        self.lbl_next.config(text="%s つぎは「%s」まで あと %s  (%s)   ／ 実行中 %d件" % (
            emoji, nxt.label, fmt_dur(rem), fmt_eta(nxt.end_ts), len(live)))

    # ---------------- 通知の見せ方 ----------------
    def test_sound(self):
        snd.play_async(self.cfg["sound_done"], self.cfg.get("volume", 0.7), SOUND_CACHE)

    def show_popup(self, title, body, urgent=True, sound_spec=None):
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.destroy()
        p = tk.Toplevel(self)
        self.popup = p
        p.title(title)
        p.configure(bg=th.BG)
        p.attributes("-topmost", True)
        p.resizable(False, False)
        w, h = 420, 210
        p.geometry("%dx%d+%d+%d" % (w, h, p.winfo_screenwidth() - w - 36, 56))
        card = th.Card(p, bg=th.BG)
        card.pack(fill="both", expand=True, padx=8, pady=8)
        b = card.body
        tk.Label(b, text=title, bg=th.CARD, fg=th.PINK_DK if urgent else th.LAV,
                 font=self.F["cute_b"], wraplength=w - 70, justify="left",
                 anchor="w").pack(fill="x", pady=(4, 6))
        tk.Label(b, text=body or "", bg=th.CARD, fg=th.INK, font=self.F["ui"],
                 wraplength=w - 70, justify="left", anchor="w").pack(fill="x")
        tk.Label(b, text=datetime.now().strftime("%H:%M:%S"), bg=th.CARD,
                 fg=th.INK_SUB, font=self.F["small"], anchor="w").pack(fill="x",
                                                                      pady=(8, 10))
        th.RoundButton(b, "とめる", lambda: self._close_popup(p), kind="primary",
                       bg=th.CARD, font=self.F["cute"]).pack()
        p.protocol("WM_DELETE_WINDOW", lambda: self._close_popup(p))
        if urgent and self.cfg.get("repeat_alarm") and self.cfg.get("sound"):
            self.alarm_on = True
            self._repeat_alarm(p, sound_spec, 0)
        p.after(180000, lambda: self._close_popup(p))

    def _repeat_alarm(self, p, sound_spec, n):
        if not p.winfo_exists() or not self.alarm_on or n > 40:
            return
        if n > 0:
            snd.play_async(sound_spec or self.cfg["sound_done"],
                           self.cfg.get("volume", 0.7), SOUND_CACHE)
        p.after(6000, lambda: self._repeat_alarm(p, sound_spec, n + 1))

    def _close_popup(self, p):
        self.alarm_on = False
        snd.stop()
        if p.winfo_exists():
            p.destroy()

    def flash_taskbar(self):
        try:
            import ctypes
            from ctypes import wintypes

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND),
                            ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT),
                            ("dwTimeout", wintypes.DWORD)]

            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            fi = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x0000000C, 8, 0)
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(fi))
        except Exception:
            pass

    # ---------------- その他 ----------------
    def open_new_dialog(self):
        NewTimerDialog(self)

    def open_settings(self):
        SettingsDialog(self)

    def apply_topmost(self):
        self.cfg["always_on_top"] = bool(self.var_top.get())
        self.attributes("-topmost", self.cfg["always_on_top"])
        self.save_cfg()

    def save_cfg(self):
        try:
            self.cfg["geometry"] = self.winfo_geometry()
        except Exception:
            pass
        save_json(CONFIG_PATH, self.cfg)

    def on_close(self):
        self.save_cfg()
        self.save_timers()
        snd.stop()
        self.destroy()


# ---------------------------------------------------------------- カード
class TimerCard(th.Card):
    def __init__(self, parent, app: App, t: BreedTimer):
        super().__init__(parent, bg=th.BG)
        self.app = app
        self.t = t
        F = app.F
        emoji, color, kname = th.KIND_STYLE.get(t.kind, ("⏰", th.PEACH, t.kind))
        self.color = color
        b = self.body

        head = tk.Frame(b, bg=th.CARD)
        head.pack(fill="x")
        th.PillBadge(head, "%s %s" % (emoji, kname), color, bg=th.CARD,
                     font=F["small"]).pack(side="left")
        tk.Label(head, text="  " + (t.label or "むめい"), bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(side="left")
        if t.species:
            tk.Label(head, text=" " + t.species, bg=th.CARD, fg=th.INK_SUB,
                     font=F["small"]).pack(side="left")
        if t.repeat:
            tk.Label(head, text=" 🔁", bg=th.CARD, fg=th.INK_SUB,
                     font=F["small"]).pack(side="left")

        btns = tk.Frame(head, bg=th.CARD)
        btns.pack(side="right")
        th.RoundButton(btns, "✕", lambda: app.remove_timer(t.id), kind="danger",
                       bg=th.CARD, font=F["small"], padx=10, pady=5).pack(side="right",
                                                                         padx=2)
        th.RoundButton(btns, "−5分", lambda: self.nudge(-300), kind="ghost",
                       bg=th.CARD, font=F["small"], padx=9, pady=5).pack(side="right",
                                                                        padx=2)
        th.RoundButton(btns, "＋5分", lambda: self.nudge(300), kind="ghost",
                       bg=th.CARD, font=F["small"], padx=9, pady=5).pack(side="right",
                                                                        padx=2)
        self.btn_pause = th.RoundButton(btns, "⏸", self.on_pause, kind="ghost",
                                        bg=th.CARD, font=F["small"], padx=11, pady=5)
        self.btn_pause.pack(side="right", padx=2)
        if t.kind == "imprint" and t.imp_index < t.imp_count:
            th.RoundButton(btns, "✔ できた", lambda: app.imprint_next(t), kind="mint",
                           bg=th.CARD, font=F["small"], padx=12,
                           pady=5).pack(side="right", padx=2)

        mid = tk.Frame(b, bg=th.CARD)
        mid.pack(fill="x", pady=(4, 0))
        self.lbl_time = tk.Label(mid, text="", bg=th.CARD, fg=th.INK, font=F["num"])
        self.lbl_time.pack(side="left")
        right = tk.Frame(mid, bg=th.CARD)
        right.pack(side="right", anchor="s", pady=(0, 5), padx=(0, 4))
        self.lbl_eta = tk.Label(right, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="e")
        self.lbl_eta.pack(anchor="e")
        self.lbl_info = tk.Label(right, text="", bg=th.CARD, fg=th.INK_SUB,
                                 font=F["small"], anchor="e")
        self.lbl_info.pack(anchor="e")

        self.bar = th.RoundProgress(b, bg=th.CARD, color=color, height=9)
        self.bar.pack(fill="x", pady=(6, 0), padx=(0, 4))
        self.lbl_note = tk.Label(b, text="", bg=th.CARD, fg=th.INK_SUB,
                                 font=F["small"], anchor="w")
        self._note_shown = False
        self.update_view(time.time())

    def on_pause(self):
        self.t.toggle_pause()
        self.app.save_timers()

    def nudge(self, sec):
        self.t.end_ts += sec
        self.t.total = max(1.0, self.t.total + sec)
        if self.t.remaining() > 0:
            self.t.done = False
            self.t.prewarned = False
        self.app.save_timers()
        self.app.rebuild_list()

    def update_view(self, now):
        t = self.t
        rem = t.remaining(now)
        if t.paused:
            self.lbl_time.config(text=fmt_dur(rem), fg=th.INK_SUB)
            self.btn_pause.set_text("▶")
            self.lbl_eta.config(text="おやすみ中")
        elif rem <= 0:
            over = -rem
            self.lbl_time.config(text="0:00" if over < 1 else fmt_dur(over), fg=th.RED)
            self.btn_pause.set_text("⏸")
            self.lbl_eta.config(text="おわりました" if over < 1 else "経過")
        else:
            self.lbl_time.config(text=fmt_dur(rem),
                                 fg=th.PINK_DK if rem <= 60 else th.INK)
            self.btn_pause.set_text("⏸")
            self.lbl_eta.config(text="%s に鳴ります" % fmt_eta(t.end_ts))
        self.bar.set(t.progress(now), th.RED if rem <= 0 and not t.paused else self.color)

        info = ""
        if t.kind == "imprint":
            if t.imp_index >= t.imp_count:
                info = "刷り込み完了 %d/%d" % (t.imp_index, t.imp_count)
            else:
                info = "つぎ %d/%d回目 (+%.1f%%) ・いま %.0f%%" % (
                    t.imp_index + 1, t.imp_count, t.imp_per, t.imp_per * t.imp_index)
            if t.mature_end:
                info += " ・成体まで %s" % fmt_dur(max(0.0, t.mature_end - now))
        elif t.kind == "mature":
            info = "進行 %.1f%%" % (t.progress(now) * 100)
            ms = t.milestone_ts
            if ms and not t.milestone_done:
                info += " ・10%%まで %s" % fmt_dur(max(0.0, ms - now))
        elif t.kind in ("hatch", "gestation") and t.chain:
            info = "終わったら成長・刷り込みも作ります"
        elif t.repeat:
            info = "%s ごとに繰り返し" % fmt_dur(t.total)
        self.lbl_info.config(text=info)

        if t.note and not self._note_shown:
            self.lbl_note.pack(fill="x", pady=(6, 0))
            self._note_shown = True
        elif not t.note and self._note_shown:
            self.lbl_note.pack_forget()
            self._note_shown = False
        self.lbl_note.config(text=t.note)


# ---------------------------------------------------------------- 音の選択部品
class SoundPicker(tk.Frame):
    """内蔵音＋自分のファイルを選ぶコンボボックス（試聴つき）"""

    def __init__(self, master, app: App, value="", bg=th.CARD, allow_default=False,
                 on_change=None):
        super().__init__(master, bg=bg)
        self.app = app
        self.on_change = on_change
        self.value = value
        self.var = tk.StringVar()
        self.combo = ttk.Combobox(self, textvariable=self.var, state="readonly",
                                  width=22, style="Cute.TCombobox",
                                  font=app.F["ui"])
        self.combo.pack(side="left")
        self.combo.bind("<<ComboboxSelected>>", self._on_pick)
        th.RoundButton(self, "▶", self.preview, kind="soft", bg=bg,
                       font=app.F["small"], padx=10, pady=5).pack(side="left", padx=4)
        th.RoundButton(self, "🎵 ファイル", self.pick_file, kind="soft", bg=bg,
                       font=app.F["small"], padx=10, pady=5).pack(side="left")
        self.allow_default = allow_default
        self.reload()

    def reload(self):
        items = []
        self.specs = []
        if self.allow_default:
            items.append("既定の音")
            self.specs.append("")
        for spec, name in snd.builtin_choices():
            items.append(name)
            self.specs.append(spec)
        for p in self.app.cfg.get("my_sounds", []):
            items.append("🎵 " + os.path.basename(p))
            self.specs.append(p)
        self.combo["values"] = items
        if self.value in self.specs:
            self.combo.current(self.specs.index(self.value))
        elif self.value:
            items.append("🎵 " + os.path.basename(self.value))
            self.specs.append(self.value)
            self.combo["values"] = items
            self.combo.current(len(items) - 1)
        else:
            self.combo.current(0)

    def _on_pick(self, _e=None):
        i = self.combo.current()
        if 0 <= i < len(self.specs):
            self.value = self.specs[i]
        if self.on_change:
            self.on_change(self.value)
        self.preview()

    def get(self):
        return self.value

    def preview(self):
        spec = self.value or self.app.cfg["sound_done"]
        snd.play_async(spec, self.app.cfg.get("volume", 0.7), SOUND_CACHE)

    def pick_file(self):
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(), title="鳴らす音のファイルを選ぶ",
            filetypes=[("音声ファイル", "*.mp3 *.wav *.m4a *.wma *.aac"),
                       ("すべてのファイル", "*.*")])
        if not path:
            return
        my = list(self.app.cfg.get("my_sounds", []))
        if path in my:
            my.remove(path)
        my.insert(0, path)
        self.app.cfg["my_sounds"] = my[:8]
        self.app.save_cfg()
        self.value = path
        self.reload()
        if self.on_change:
            self.on_change(self.value)
        self.preview()


# ---------------------------------------------------------------- 新規ダイアログ
class NewTimerDialog(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.F = app.F
        self.sp = None
        self.calc = None
        self.title("新しいタイマー")
        self.configure(bg=th.BG)
        self.geometry("800x620")
        self.transient(app)
        self.attributes("-topmost", bool(app.cfg["always_on_top"]))

        sw = tk.Frame(self, bg=th.BG)
        sw.pack(fill="x", padx=18, pady=(16, 8))
        self.btn_free = th.RoundButton(sw, "⏰ 自由タイマー",
                                       lambda: self.switch("free"), kind="primary",
                                       bg=th.BG, font=self.F["cute"])
        self.btn_free.pack(side="left", padx=(0, 8))
        self.btn_ark = th.RoundButton(sw, "🦖 ARKの恐竜から",
                                      lambda: self.switch("ark"), kind="soft",
                                      bg=th.BG, font=self.F["cute"])
        self.btn_ark.pack(side="left")

        self.holder = tk.Frame(self, bg=th.BG)
        self.holder.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.page_free = th.Card(self.holder, bg=th.BG)
        self.page_ark = th.Card(self.holder, bg=th.BG)
        self._build_free(self.page_free.body)
        self._build_ark(self.page_ark.body)
        self.switch("free")

    def switch(self, which):
        self.page_free.pack_forget()
        self.page_ark.pack_forget()
        if which == "free":
            self.page_free.pack(fill="both", expand=True)
            self.btn_free.itemconfigure(self.btn_free.shape, fill=th.PINK)
            self.btn_ark.itemconfigure(self.btn_ark.shape, fill=th.BG_SOFT)
            self.btn_free.fill, self.btn_ark.fill = th.PINK, th.BG_SOFT
            self.btn_free.itemconfigure(self.btn_free.label, fill="#FFFFFF")
            self.btn_ark.itemconfigure(self.btn_ark.label, fill=th.INK)
        else:
            self.page_ark.pack(fill="both", expand=True)
            self.btn_ark.itemconfigure(self.btn_ark.shape, fill=th.PINK)
            self.btn_free.itemconfigure(self.btn_free.shape, fill=th.BG_SOFT)
            self.btn_ark.fill, self.btn_free.fill = th.PINK, th.BG_SOFT
            self.btn_ark.itemconfigure(self.btn_ark.label, fill="#FFFFFF")
            self.btn_free.itemconfigure(self.btn_free.label, fill=th.INK)
            self.refresh_list()

    # ------------------------------------------------ 自由タイマー
    def _build_free(self, f):
        F = self.F
        tk.Label(f, text="なまえ", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(anchor="w")
        self.f_label = tk.StringVar()
        e = th.soft_entry(f, self.f_label, font=F["cute"])
        e.pack(fill="x", ipady=6, pady=(2, 14))
        e.focus_set()

        self.f_mode = tk.StringVar(value="rel")
        self._radio(f, "この時間だけ後に鳴らす", self.f_mode, "rel").pack(anchor="w")

        r1 = tk.Frame(f, bg=th.CARD)
        r1.pack(anchor="w", padx=26, pady=(6, 4))
        self.f_h = tk.StringVar(value="0")
        self.f_m = tk.StringVar(value="10")
        self.f_s = tk.StringVar(value="0")
        for var, unit in ((self.f_h, "時間"), (self.f_m, "分"), (self.f_s, "秒")):
            sp = tk.Spinbox(r1, from_=0, to=999, textvariable=var, width=4,
                            bg=th.FIELD, fg=th.INK, font=("Segoe UI Semibold", 17),
                            relief="flat", bd=0, justify="center",
                            buttonbackground=th.BG_SOFT, highlightthickness=2,
                            highlightbackground=th.LINE, highlightcolor=th.PINK,
                            command=lambda: self.f_mode.set("rel"))
            sp.pack(side="left", ipady=3)
            sp.bind("<FocusIn>", lambda e: self.f_mode.set("rel"))
            tk.Label(r1, text=" %s  " % unit, bg=th.CARD, fg=th.INK_SUB,
                     font=F["cute"]).pack(side="left")

        q = tk.Frame(f, bg=th.CARD)
        q.pack(anchor="w", padx=26, pady=(2, 14))
        for txt, sec in (("1分", 60), ("3分", 180), ("5分", 300), ("10分", 600),
                         ("15分", 900), ("30分", 1800), ("1時間", 3600),
                         ("3時間", 10800)):
            th.Chip(q, txt, lambda s=sec: self._set_rel(s), bg=th.CARD,
                    font=F["small"]).pack(side="left", padx=3)

        self._radio(f, "指定した時刻に鳴らす", self.f_mode, "abs").pack(anchor="w")
        r2 = tk.Frame(f, bg=th.CARD)
        r2.pack(anchor="w", padx=26, pady=(6, 2))
        self.f_clock = tk.StringVar(value=datetime.now().strftime("%H:%M"))
        ec = th.soft_entry(r2, self.f_clock, width=10,
                           font=("Segoe UI Semibold", 17))
        ec.pack(side="left", ipady=3)
        ec.bind("<FocusIn>", lambda e: self.f_mode.set("abs"))
        tk.Label(r2, text="   21:30 / 21:30:00 / 8/5 21:30 / 25:00(=翌1時)",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(side="left")
        tk.Label(f, text="     時刻だけ書いて既に過ぎていたら「明日」になります",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w",
                                                                  pady=(0, 12))

        row = tk.Frame(f, bg=th.CARD)
        row.pack(fill="x", pady=(0, 10))
        tk.Label(row, text="音  ", bg=th.CARD, fg=th.INK_SUB, font=F["cute"],
                 anchor="w").pack(side="left", pady=4)
        self.f_sound = SoundPicker(row, self.app, value="", allow_default=True)
        self.f_sound.pack(side="left")

        self.f_repeat = tk.BooleanVar(value=False)
        self._check(f, "鳴ったあと同じ長さで繰り返す 🔁",
                    self.f_repeat).pack(anchor="w")

        row3 = tk.Frame(f, bg=th.CARD)
        row3.pack(fill="x", pady=(8, 0))
        tk.Label(row3, text="メモ  ", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")
        self.f_note = tk.StringVar()
        th.soft_entry(row3, self.f_note).pack(side="left", fill="x", expand=True,
                                              ipady=4)

        self.f_prev = tk.Label(f, text="", bg=th.CARD, fg=th.PINK_DK,
                               font=F["cute_b"], anchor="w")
        self.f_prev.pack(fill="x", pady=(14, 0))

        btm = tk.Frame(f, bg=th.CARD)
        btm.pack(side="bottom", fill="x", pady=(10, 0))
        th.RoundButton(btm, "つくる", self.create_free, kind="primary", bg=th.CARD,
                       font=F["cute_b"], padx=30).pack(side="right")
        th.RoundButton(btm, "やめる", self.destroy, kind="soft", bg=th.CARD,
                       font=F["cute"]).pack(side="right", padx=8)

        for v in (self.f_mode, self.f_h, self.f_m, self.f_s, self.f_clock):
            v.trace_add("write", lambda *a: self._free_preview())
        self._free_preview()

    def _radio(self, parent, text, var, value):
        return tk.Radiobutton(parent, text=text, variable=var, value=value,
                              bg=th.CARD, fg=th.INK, activebackground=th.CARD,
                              activeforeground=th.INK, selectcolor=th.FIELD,
                              font=self.F["cute"], bd=0, highlightthickness=0,
                              anchor="w")

    def _check(self, parent, text, var, cmd=None):
        return tk.Checkbutton(parent, text=text, variable=var, command=cmd,
                              bg=th.CARD, fg=th.INK, activebackground=th.CARD,
                              activeforeground=th.INK, selectcolor=th.FIELD,
                              font=self.F["cute"], bd=0, highlightthickness=0,
                              anchor="w")

    def _set_rel(self, sec):
        self.f_mode.set("rel")
        h, rem = divmod(int(sec), 3600)
        m, s = divmod(rem, 60)
        self.f_h.set(str(h))
        self.f_m.set(str(m))
        self.f_s.set(str(s))

    def _free_seconds(self):
        if self.f_mode.get() == "abs":
            ts = parse_clock(self.f_clock.get())
            if ts is None:
                return None, "時刻の書き方がわかりません（例 21:30）"
            sec = ts - time.time()
            if sec <= 0:
                return None, "その時刻はもう過ぎています"
            return sec, None
        try:
            sec = (float(self.f_h.get() or 0) * 3600 + float(self.f_m.get() or 0) * 60
                   + float(self.f_s.get() or 0))
        except ValueError:
            return None, "数字で入れてください"
        if sec <= 0:
            return None, "0秒より長くしてください"
        return sec, None

    def _free_preview(self):
        sec, err = self._free_seconds()
        if err:
            self.f_prev.config(text="⚠ " + err, fg=th.INK_SUB)
        else:
            self.f_prev.config(text="→ %s後、%s に鳴ります 🔔" % (
                fmt_dur(sec), fmt_eta(time.time() + sec)), fg=th.PINK_DK)

    def create_free(self):
        sec, err = self._free_seconds()
        if err:
            messagebox.showwarning(APP_NAME, err, parent=self)
            return
        t = BreedTimer("custom", self.f_label.get().strip() or "タイマー", sec)
        t.repeat = bool(self.f_repeat.get())
        t.sound = self.f_sound.get()
        t.note = self.f_note.get().strip()
        self.app.add_timer(t)
        self.destroy()

    # ------------------------------------------------ ARK
    def _build_ark(self, f):
        F = self.F
        left = tk.Frame(f, bg=th.CARD)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="恐竜をさがす（日本語でも英語でも）", bg=th.CARD,
                 fg=th.INK_SUB, font=F["small"]).pack(anchor="w")
        self.var_q = tk.StringVar()
        ent = th.soft_entry(left, self.var_q, font=F["cute"])
        ent.pack(fill="x", ipady=5, pady=(2, 8))
        ent.bind("<KeyRelease>", lambda e: self.refresh_list())
        self.lst = tk.Listbox(left, bg=th.FIELD, fg=th.INK, selectbackground=th.PINK,
                              selectforeground="#FFFFFF", borderwidth=0,
                              highlightthickness=0, font=F["ui"], activestyle="none")
        self.lst.pack(fill="both", expand=True)
        self.lst.bind("<<ListboxSelect>>", lambda e: self.on_select())
        self.lst.bind("<Double-Button-1>", lambda e: self.create_ark())

        right = tk.Frame(f, bg=th.CARD, width=330)
        right.pack(side="right", fill="y", padx=(14, 0))
        right.pack_propagate(False)
        tk.Label(right, text="いまの倍率だとこうなります", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        self.lbl_calc = tk.Label(right, text="恐竜をえらんでね", bg=th.FIELD,
                                 fg=th.INK, font=F["ui"], justify="left", anchor="nw",
                                 padx=12, pady=10, height=8)
        self.lbl_calc.pack(fill="x", pady=(6, 12))

        tk.Label(right, text="なまえ（個体のあだ名）", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(anchor="w")
        self.var_label = tk.StringVar()
        th.soft_entry(right, self.var_label, font=F["cute"]).pack(fill="x", ipady=5,
                                                                 pady=(2, 12))

        tk.Label(right, text="つくるタイマー", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(anchor="w")
        self.kv = {}
        for key, text in (("hatch", "🥚 孵化"), ("gestation", "🌸 妊娠"),
                          ("mature", "🌱 成長"), ("imprint", "💗 刷り込み"),
                          ("matingcd", "💞 再交配CD")):
            v = tk.BooleanVar(value=key in ("hatch", "gestation"))
            self.kv[key] = v
            self._check(right, text, v).pack(anchor="w")

        tk.Label(right, text="", bg=th.CARD).pack(pady=2)
        self.var_start = tk.StringVar(value="now")
        self._radio(right, "今から（産みたて・生まれたて）", self.var_start,
                    "now").pack(anchor="w")
        rowl = tk.Frame(right, bg=th.CARD)
        rowl.pack(anchor="w", fill="x")
        self._radio(rowl, "残り時間から", self.var_start, "left").pack(side="left")
        self.var_left = tk.StringVar()
        th.soft_entry(rowl, self.var_left, width=9).pack(side="left", padx=4, ipady=3)
        tk.Label(right, text="   例: 1:23:45 / 25m / 90（=90分）", bg=th.CARD,
                 fg=th.INK_SUB, font=F["small"]).pack(anchor="w")

        btm = tk.Frame(right, bg=th.CARD)
        btm.pack(side="bottom", fill="x", pady=(12, 0))
        th.RoundButton(btm, "つくる", self.create_ark, kind="primary", bg=th.CARD,
                       font=F["cute_b"], padx=26).pack(side="right")
        th.RoundButton(btm, "やめる", self.destroy, kind="soft", bg=th.CARD,
                       font=F["cute"]).pack(side="right", padx=8)

    def refresh_list(self):
        self.results = self.app.db.search(self.var_q.get())
        self.lst.delete(0, "end")
        for s in self.results[:400]:
            jp = s.get("jp", "")
            self.lst.insert("end", "  %s%s" % (
                s["name"], ("   " + jp.split(" ")[0]) if jp else ""))
        if self.results:
            self.lst.selection_clear(0, "end")
            self.lst.selection_set(0)
            self.on_select()

    def on_select(self):
        sel = self.lst.curselection()
        if not sel:
            return
        self.sp = self.results[sel[0]]
        c = calc_times(self.sp, self.app.cfg)
        self.calc = c
        lines = []
        if c["hatch"] > 0:
            lines.append("🥚 孵化    %s" % fmt_dur(c["hatch"]))
        if c["gestation"] > 0:
            lines.append("🌸 妊娠    %s" % fmt_dur(c["gestation"]))
        lines.append("🌱 成長    %s" % fmt_dur(c["mature"]))
        lines.append("    10%%で放置OK  %s" % fmt_dur(c["juvenile"]))
        if c["imprint_count"]:
            lines.append("💗 刷り込み %s ごと × %d回" % (
                fmt_dur(c["imprint_interval"]), c["imprint_count"]))
            lines.append("    1回 +%.1f%% ・ぜんぶで %.0f%%" % (
                c["imprint_per"], min(100.0, c["imprint_per"] * c["imprint_count"])))
        lines.append("💞 再交配  %s 〜 %s" % (fmt_dur(c["cd_lo"]), fmt_dur(c["cd_hi"])))
        self.lbl_calc.config(text="\n".join(lines))
        self.kv["hatch"].set(c["hatch"] > 0)
        self.kv["gestation"].set(c["gestation"] > 0)

    def create_ark(self):
        if not self.sp:
            messagebox.showwarning(APP_NAME, "恐竜をえらんでください", parent=self)
            return
        kinds = tuple(k for k, v in self.kv.items() if v.get())
        if not kinds:
            messagebox.showwarning(APP_NAME, "つくるタイマーを1つ以上えらんでください",
                                   parent=self)
            return
        label = self.var_label.get().strip() or self.sp["name"]
        offset = 0.0
        if self.var_start.get() == "left":
            left = parse_duration(self.var_left.get())
            if left is None:
                messagebox.showwarning(APP_NAME, "残り時間の書き方がわかりません（例 1:23:45）",
                                       parent=self)
                return
            base = {"hatch": self.calc["hatch"], "gestation": self.calc["gestation"],
                    "mature": self.calc["mature"],
                    "imprint": self.calc["imprint_interval"],
                    "matingcd": self.calc["cd_lo"]}.get(kinds[0], left)
            offset = max(0.0, base - left)
        made = self.app.make_timers(self.sp, label, self.calc, kinds, offset=offset)
        if not made:
            messagebox.showinfo(APP_NAME, "この恐竜にはそのタイマーがありません", parent=self)
            return
        for t in made:
            self.app.timers.append(t)
        self.app.rebuild_list()
        self.app.save_timers()
        self.destroy()


# ---------------------------------------------------------------- 設定
class SettingsDialog(tk.Toplevel):
    MULTS = [
        ("egg_hatch_speed", "EggHatchSpeedMultiplier（孵化・妊娠）"),
        ("baby_mature_speed", "BabyMatureSpeedMultiplier（成長）"),
        ("cuddle_interval_mult", "BabyCuddleIntervalMultiplier（刷り込み間隔）"),
        ("mating_interval_mult", "MatingIntervalMultiplier（再交配CD）"),
        ("imprint_amount_mult", "BabyImprintAmountMultiplier（刷り込み量）"),
    ]

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.F = app.F
        self.title("設定")
        self.configure(bg=th.BG)
        self.geometry("560x624")
        self.transient(app)
        self.attributes("-topmost", bool(app.cfg["always_on_top"]))

        sw = tk.Frame(self, bg=th.BG)
        sw.pack(fill="x", padx=18, pady=(16, 8))
        self.b1 = th.RoundButton(sw, "🔔 音と通知", lambda: self.switch("snd"),
                                 kind="primary", bg=th.BG, font=self.F["cute"])
        self.b1.pack(side="left", padx=(0, 8))
        self.b2 = th.RoundButton(sw, "🦖 ARK倍率", lambda: self.switch("ark"),
                                 kind="soft", bg=th.BG, font=self.F["cute"])
        self.b2.pack(side="left")

        self.holder = tk.Frame(self, bg=th.BG)
        self.holder.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.p1 = th.Card(self.holder, bg=th.BG)
        self.p2 = th.Card(self.holder, bg=th.BG)
        self._build_sound(self.p1.body)
        self._build_ark(self.p2.body)

        btm = tk.Frame(self, bg=th.BG)
        btm.pack(fill="x", padx=18, pady=(0, 14))
        th.RoundButton(btm, "保存する", self.save, kind="primary", bg=th.BG,
                       font=self.F["cute_b"], padx=28).pack(side="right")
        th.RoundButton(btm, "やめる", self.destroy, kind="soft", bg=th.BG,
                       font=self.F["cute"]).pack(side="right", padx=8)
        tk.Label(btm, text="恐竜データ %d種" % len(app.db.species), bg=th.BG,
                 fg=th.INK_SUB, font=self.F["small"]).pack(side="left")
        self.switch("snd")

    def switch(self, which):
        self.p1.pack_forget()
        self.p2.pack_forget()
        on, off = (self.b1, self.b2) if which == "snd" else (self.b2, self.b1)
        (self.p1 if which == "snd" else self.p2).pack(fill="both", expand=True)
        on.fill = th.PINK
        off.fill = th.BG_SOFT
        on.itemconfigure(on.shape, fill=th.PINK)
        on.itemconfigure(on.label, fill="#FFFFFF")
        off.itemconfigure(off.shape, fill=th.BG_SOFT)
        off.itemconfigure(off.label, fill=th.INK)

    def _check(self, parent, text, var):
        return tk.Checkbutton(parent, text=text, variable=var, bg=th.CARD, fg=th.INK,
                              activebackground=th.CARD, activeforeground=th.INK,
                              selectcolor=th.FIELD, font=self.F["cute"], bd=0,
                              highlightthickness=0, anchor="w")

    def _build_sound(self, f):
        F = self.F
        cfg = self.app.cfg
        tk.Label(f, text="音量", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        row = tk.Frame(f, bg=th.CARD)
        row.pack(fill="x", pady=(4, 14))
        self.vol = cfg.get("volume", 0.7)
        self.slider = th.RoundSlider(row, value=self.vol, command=self._vol_changed,
                                     bg=th.CARD)
        self.slider.pack(side="left", fill="x", expand=True)
        self.lbl_vol = tk.Label(row, text="", bg=th.CARD, fg=th.PINK_DK,
                                font=F["cute_b"], width=5)
        self.lbl_vol.pack(side="left", padx=6)
        th.RoundButton(row, "▶ 試聴", self._preview_vol, kind="soft", bg=th.CARD,
                       font=F["small"], padx=12, pady=5).pack(side="left")
        self._vol_changed(self.vol)

        tk.Label(f, text="鳴ったときの音", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        self.pick_done = SoundPicker(f, self.app, value=cfg.get("sound_done", ""))
        self.pick_done.pack(anchor="w", pady=(4, 12))

        tk.Label(f, text="予告のときの音", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        self.pick_pre = SoundPicker(f, self.app, value=cfg.get("sound_prewarn", ""))
        self.pick_pre.pack(anchor="w", pady=(4, 4))
        tk.Label(f, text="mp3 / wav / m4a などを「🎵 ファイル」から選べます",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w",
                                                                  pady=(0, 14))

        tk.Label(f, text="知らせかた", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        self.v_sound = tk.BooleanVar(value=bool(cfg["sound"]))
        self.v_popup = tk.BooleanVar(value=bool(cfg["popup"]))
        self.v_toast = tk.BooleanVar(value=bool(cfg["toast"]))
        self.v_rep = tk.BooleanVar(value=bool(cfg["repeat_alarm"]))
        self.v_chain = tk.BooleanVar(value=bool(cfg["auto_chain"]))
        for text, v in (("音を鳴らす", self.v_sound),
                        ("画面のすみにポップアップを出す", self.v_popup),
                        ("Windowsの通知も出す", self.v_toast),
                        ("「とめる」を押すまで音をくり返す", self.v_rep),
                        ("孵化・出産のあと成長／刷り込みも自動で作る", self.v_chain)):
            self._check(f, text, v).pack(anchor="w")

        row2 = tk.Frame(f, bg=th.CARD)
        row2.pack(anchor="w", pady=(8, 0))
        tk.Label(row2, text="何秒前に予告する？（0でなし）", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        self.v_pre = tk.StringVar(value=str(int(cfg.get("prewarn_sec") or 0)))
        th.soft_entry(row2, self.v_pre, width=6).pack(side="left", padx=8, ipady=3)

    def _vol_changed(self, v):
        self.vol = v
        self.lbl_vol.config(text="%d%%" % round(v * 100))
        self.app.cfg["volume"] = v  # 試聴にすぐ反映させる

    def _preview_vol(self):
        snd.play_async(self.pick_done.get() or snd.DEFAULT_DONE,
                       self.vol, SOUND_CACHE)

    def _build_ark(self, f):
        F = self.F
        tk.Label(f, text="サーバー倍率", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        tk.Label(f, text="GSMの「⚡dynamic設定」と同じ値を入れてください",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w",
                                                                  pady=(0, 8))
        self.vars = {}
        for key, text in self.MULTS:
            row = tk.Frame(f, bg=th.CARD)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=text, bg=th.CARD, fg=th.INK, font=F["ui"],
                     anchor="w", width=40).pack(side="left")
            v = tk.StringVar(value=str(self.app.cfg.get(key)))
            self.vars[key] = v
            th.soft_entry(row, v, width=8).pack(side="left", ipady=3)

        self.v_gest = tk.BooleanVar(
            value=bool(self.app.cfg.get("gestation_uses_hatch_mult", True)))
        self._check(f, "妊娠時間にも EggHatchSpeedMultiplier を掛ける",
                    self.v_gest).pack(anchor="w", pady=(10, 0))
        tk.Label(f, text="\n刷り込み間隔 = 8時間 × BabyCuddleIntervalMultiplier\n"
                         "刷り込み回数 = 成長時間 ÷ 刷り込み間隔（切り捨て）",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"],
                 justify="left").pack(anchor="w")

    def save(self):
        try:
            for key, _ in self.MULTS:
                val = float(self.vars[key].get())
                if val <= 0:
                    raise ValueError(key)
                self.app.cfg[key] = val
            self.app.cfg["prewarn_sec"] = max(0, int(float(self.v_pre.get())))
        except ValueError:
            messagebox.showwarning(APP_NAME, "倍率は0より大きい数字で入れてください",
                                   parent=self)
            return
        c = self.app.cfg
        c["gestation_uses_hatch_mult"] = bool(self.v_gest.get())
        c["sound"] = bool(self.v_sound.get())
        c["popup"] = bool(self.v_popup.get())
        c["toast"] = bool(self.v_toast.get())
        c["repeat_alarm"] = bool(self.v_rep.get())
        c["auto_chain"] = bool(self.v_chain.get())
        c["volume"] = self.vol
        c["sound_done"] = self.pick_done.get() or snd.DEFAULT_DONE
        c["sound_prewarn"] = self.pick_pre.get() or snd.DEFAULT_PREWARN
        self.app.save_cfg()
        self.destroy()


def main():
    if not os.path.exists(os.path.join(DATA_DIR, "species.json")):
        print("data/species.json がありません。tools/build_species_db.py を実行してください。")
    App().mainloop()


if __name__ == "__main__":
    main()
