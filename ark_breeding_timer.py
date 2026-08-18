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
from tkinter import font as tkfont

import afk
import gametime
import macro
import sounds as snd
import serverwatch
import taming
import theme as th
import updater
from afk_page import AfkPage
from gametime_page import GameTimePage
from macro_page import MacroPage

APP_NAME = "ARK Breeding Timer"
APP_VERSION = "1.23.0"


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
CHECKLIST_PATH = os.path.join(STATE_DIR, "checklist.json")
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
    # テイム関係のサーバー倍率
    "taming_speed": 1.0,          # TamingSpeedMultiplier
    "food_drain": 1.0,            # DinoCharacterFoodDrainMultiplier
    "wild_food_drain": 1.0,       # WildDinoCharacterFoodDrainMultiplier
    "torpor_drain": 1.0,          # WildDinoTorporDrainMultiplier
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
    # ポップアップが自分で消えるまでの秒数（0 = 「とめる」を押すまで消えない）
    "popup_close_prewarn": 8,
    "popup_close_done": 0,
    "prewarn_sec": 60,
    "auto_chain": True,
    # 操作
    "confirm_delete": True,   # ✕ を押したとき確認するか
    "auto_clear_done": True,  # 終わったタイマーを自動で消すか
    "auto_clear_sec": 600,    # 終わってから何秒で消すか
    "quick_buttons": [        # 「さくっと」のワンクリックボタン（設定で変えられる）
        {"label": "1分", "sec": 60},
        {"label": "3分", "sec": 180},
        {"label": "5分", "sec": 300},
        {"label": "10分", "sec": 600},
        {"label": "15分", "sec": 900},
        {"label": "30分", "sec": 1800},
        {"label": "1時間", "sec": 3600},
    ],
    # AFK防止（放置キック対策のキー送信）
    "afk_key": afk.DEFAULT_KEY,
    "afk_interval": 120,          # 何秒ごとに送るか
    "afk_times": 2,               # 1回あたり何連打
    "afk_gap_ms": 60,             # 連打の間隔
    "afk_target": "ArkAscended.exe",   # 送る相手のexe名
    "afk_mode": afk.DEFAULT_MODE,      # foreground / swap / post / always
    # マクロ（連射）
    "macro_action": macro.DEFAULT_ACTION,   # left / right / middle / key
    "macro_key_vk": 0,
    "macro_key_scan": 0,
    "macro_interval_ms": 100,
    "macro_hold_ms": 20,
    "macro_limit": 0,                  # 0 = ずっと
    "macro_target": "ArkAscended.exe",
    "macro_only_target": True,
    "macro_hotkey_on": True,
    "macro_hotkey_mods": macro.MOD_CONTROL,
    "macro_hotkey_vk": 0x52,           # R
    # ゲーム内時計（マップごとに、合わせた時刻・進む速さ・見張るサーバー）
    "game_clock": {},        # 昔の1つだけの形（引き継ぎ用）
    "game_clocks": {},
    "watch_interval": 60,    # 死活を見に行く間隔（秒）
    # 画面
    "always_on_top": True,
    "geometry": "980x700",
    "page": "timers",         # 最後に開いていたページ
    "mini_geometry": "300x320",
    "mini_page": "timers",
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
        self.sound = kw.get("sound", "")   # "" なら既定音
        self.note = kw.get("note", "")
        # ---- くり返し ----
        self.repeat = bool(kw.get("repeat", False))
        self.repeat_count = int(kw.get("repeat_count", 0) or 0)  # 0 = ずっと
        self.repeat_done = int(kw.get("repeat_done", 0) or 0)    # 鳴った回数
        self.repeat_every = float(kw.get("repeat_every", 0) or 0)  # 0 = 最初と同じ長さ
        # ---- タイマーごとの鳴らし方（ミニ表示から変えられる）----
        # volume は None なら全体設定に従う
        v = kw.get("volume")
        self.volume = None if v is None else max(0.0, min(1.0, float(v)))
        self.sound_on = bool(kw.get("sound_on", True))    # 音を出すか
        self.center = bool(kw.get("center", False))       # 画面中央に大きく出すか

    def eff_volume(self, default):
        return default if self.volume is None else self.volume

    def repeat_interval(self):
        """次にセットし直す長さ。repeat_every が未指定なら今の長さのまま。"""
        return self.repeat_every if self.repeat_every > 0 else self.total

    def repeat_text(self):
        """カードに出す「くり返し」の説明。"""
        if not self.repeat:
            return ""
        every = fmt_dur(self.repeat_interval())
        if self.repeat_count > 0:
            return "🔁 %s ごと %d/%d回" % (every, min(self.repeat_done,
                                                     self.repeat_count),
                                          self.repeat_count)
        return "🔁 %s ごと（ずっと）" % every

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
              "chain", "repeat", "repeat_count", "repeat_done", "repeat_every",
              "sound", "note", "volume", "sound_on", "center")

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

    def fire(self, title, body, urgent=True, sound_spec=None, timer=None):
        """timer を渡すと、そのタイマー個別の音量・音の有無・中央表示に従う。"""
        cfg = self.app.cfg
        vol = cfg.get("volume", 0.7)
        sound_on = bool(cfg.get("sound"))
        center = False
        if timer is not None:
            vol = timer.eff_volume(vol)
            sound_on = sound_on and timer.sound_on
            center = bool(timer.center)

        if sound_on:
            spec = sound_spec or (cfg["sound_done"] if urgent else cfg["sound_prewarn"])
            snd.play_async(spec, vol, SOUND_CACHE)
        if cfg.get("toast"):
            threading.Thread(target=self._toast, args=(title, body), daemon=True).start()
        if cfg.get("popup"):
            self.app.show_popup(title, body, urgent, sound_spec,
                                center=center, volume=vol, sound_on=sound_on)
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
# ---------------------------------------------------------------- チェックリスト
CHECK_STATES = ("ok", "hold", "ng")
CHECK_MARK = {"ok": "✓", "hold": "△", "ng": "✗"}
CHECK_COLOR = {"ok": th.MINT, "hold": th.LEMON, "ng": th.RED}
CHECK_TITLE = {"ok": "完了", "hold": "保留", "ng": "中止"}
# 「やること」は印のついていないものだけ。印を押した時点でここから消え、
# それぞれのタブへ移る。全部まとめて見たいときは「すべて」。
CHECK_FILTERS = (("todo", "やること"), ("ok", "✓ 完了"), ("hold", "△ 保留"),
                 ("ng", "✗ 中止"), ("all", "すべて"))


class FlowFrame(tk.Frame):
    """幅に合わせて子を折り返して並べる入れ物。

    小さいウィンドウでもボタンやチップがはみ出さないようにするためのもの。
    子は add() で渡す（place で配置するので pack/grid は使わない）。
    """

    def __init__(self, master, bg=th.BG, gap_x=5, gap_y=5, **kw):
        super().__init__(master, bg=bg, **kw)
        self._kids = []
        self._gap_x, self._gap_y = gap_x, gap_y
        self._last_w = 0
        self.bind("<Configure>", self._on_configure)

    def add(self, widget, gap_x=None):
        self._kids.append((widget, self._gap_x if gap_x is None else gap_x))
        widget.place(x=0, y=0)
        self.after_idle(self._relayout)
        return widget

    def clear(self):
        for w, _gap in self._kids:
            w.destroy()
        self._kids = []

    def _on_configure(self, e):
        if e.width != self._last_w:
            self._last_w = e.width
            self._relayout()

    def _relayout(self):
        width = self.winfo_width()
        if width <= 1 or not self._kids:
            return
        # まず行に振り分けて、そのあと各行の高さの中央に置く
        rows, cur, x = [], [], 0
        for w, gap in self._kids:
            try:
                ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
            except tk.TclError:
                continue
            if cur and x + ww > width:
                rows.append(cur)
                cur, x = [], 0
            cur.append((w, ww, wh, gap))
            x += ww + gap
        if cur:
            rows.append(cur)

        y = 0
        for row in rows:
            row_h = max(wh for _, _, wh, _ in row)
            x = 0
            for w, ww, wh, gap in row:
                w.place(x=x, y=y + (row_h - wh) // 2)
                x += ww + gap
            y += row_h + self._gap_y
        need = max(0, y - self._gap_y)
        if need > 0 and self.winfo_reqheight() != need:
            self.configure(height=need)


class Pill(tk.Canvas):
    """角丸のトグル。ページ切替タブと絞り込みチップの両方に使う。"""

    def __init__(self, master, text, command, bg=th.BG, font=None,
                 counted=False, padx=14, pady=7):
        self.font = font or th.F.get("small", (th.JP, 9))
        fo = tkfont.Font(font=self.font)
        self.base_text = text
        w = fo.measure(text + ("  99" if counted else "")) + padx * 2
        h = fo.metrics("linespace") + pady * 2
        super().__init__(master, width=w, height=h, bg=bg,
                         highlightthickness=0, bd=0)
        self.command = command
        self.active = False
        self.shape = th.round_rect(self, 1, 1, w - 1, h - 1, h / 2,
                                   fill=th.CARD, outline=th.LINE, width=1)
        self.label = self.create_text(w / 2, h / 2 + 1, text=text,
                                      fill=th.INK_SUB, font=self.font)
        self.bind("<ButtonRelease-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.configure(cursor="hand2")

    def _hover(self, on):
        if not self.active:
            self.itemconfigure(self.shape, fill="#FFF0F6" if on else th.CARD)

    def update_view(self, active, count=None):
        self.active = active
        txt = self.base_text if count is None else "%s  %d" % (self.base_text, count)
        self.itemconfigure(self.label, text=txt)
        if active:
            self.itemconfigure(self.shape, fill=th.PINK, outline=th.PINK)
            self.itemconfigure(self.label, fill="#FFFFFF")
        else:
            self.itemconfigure(self.shape, fill=th.CARD, outline=th.LINE)
            self.itemconfigure(self.label, fill=th.INK_SUB)


class MarkButton(tk.Canvas):
    """✓ / △ / ✗ の小さな四角ボタン。押されている間だけ色が付く。"""

    SIZE = 30

    def __init__(self, master, state, command, bg=th.CARD):
        super().__init__(master, width=self.SIZE, height=self.SIZE,
                         bg=bg, highlightthickness=0, bd=0)
        self.state_key = state
        self.command = command
        self.active = False
        self.color = CHECK_COLOR[state]
        self.shape = th.round_rect(self, 1, 1, self.SIZE - 1, self.SIZE - 1, 8,
                                   fill=th.CARD, outline=th.LINE, width=1)
        self.text = self.create_text(self.SIZE / 2, self.SIZE / 2 + 1,
                                     text=CHECK_MARK[state], fill=th.INK_SUB,
                                     font=th.F.get("cute", (th.JP, 11)))
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonRelease-1>", lambda e: self.command(self.state_key))
        self.configure(cursor="hand2")

    def _hover(self, on):
        if not self.active:
            self.itemconfigure(self.shape, outline=self.color if on else th.LINE)

    def set_active(self, on):
        self.active = on
        if on:
            self.itemconfigure(self.shape, fill=self.color, outline=self.color)
            self.itemconfigure(self.text, fill="#FFFFFF")
        else:
            self.itemconfigure(self.shape, fill=th.CARD, outline=th.LINE)
            self.itemconfigure(self.text, fill=th.INK_SUB)


def load_checklist():
    """保存済みのチェックリストを読む（壊れていても落ちないように）。"""
    out = []
    for it in load_json(CHECKLIST_PATH, []):
        try:
            text = str(it.get("text", "")).strip()
            if not text:
                continue
            st = it.get("state")
            out.append({"text": text,
                        "state": st if st in CHECK_STATES else None})
        except AttributeError:
            pass
    return out


class ChecklistPage(tk.Frame):
    """✓完了 / △保留 / ✗中止 の3状態と、状態ごとの絞り込みだけの簡単な一覧。

    本体とミニ表示の両方に置けるよう、項目そのものは App が持ち、
    この画面はそれを映すだけにしてある（片方で変えたらもう片方も更新される）。
    """

    def __init__(self, master, app, compact=False):
        super().__init__(master, bg=th.BG)
        self.app = app
        self.filter = "todo"
        self._compact = compact
        app.checklist_pages.append(self)
        self._build()
        if compact:
            self.lbl_hint.pack_forget()
        self.render()

    @property
    def items(self):
        return self.app.checklist_items

    def save(self):
        self.app.save_checklist()

    # ---- 画面 ----
    def _build(self):
        F = th.F
        head = tk.Frame(self, bg=th.BG)
        head.pack(fill="x", pady=(0, 8))
        self.lbl_count = tk.Label(head, text="", bg=th.BG, fg=th.INK_SUB,
                                  font=F["small"])
        self.lbl_count.pack(side="right", anchor="n")
        self.lbl_hint = tk.Label(
            head, text="印を押すと「やること」から外れます　"
                       "もう一度押すと戻ります",
            bg=th.BG, fg=th.INK_SUB, font=F["small"], anchor="w", justify="left")
        self.lbl_hint.pack(side="left", fill="x", expand=True)
        head.bind("<Configure>", lambda e: self.lbl_hint.configure(
            wraplength=max(120, e.width - 80)))

        add = tk.Frame(self, bg=th.BG)
        add.pack(fill="x", pady=(0, 10))
        self.var_new = tk.StringVar()
        self.entry = th.soft_entry(add, textvariable=self.var_new, bg=th.BG,
                                   font=F["ui"])
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", lambda e: self.add())
        th.RoundButton(add, "追加", self.add, kind="primary", bg=th.BG,
                       font=F["cute"], padx=18).pack(side="left", padx=(8, 0))

        fbar = FlowFrame(self, bg=th.BG)
        fbar.pack(fill="x", pady=(0, 8))
        self.chips = {}
        for key, label in CHECK_FILTERS:
            self.chips[key] = fbar.add(
                Pill(fbar, label, lambda k=key: self.set_filter(k), bg=th.BG,
                     counted=True))

        wrap = tk.Frame(self, bg=th.BG)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=th.BG, highlightthickness=0, bd=0)
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview,
                           style="Cute.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=th.BG)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win, width=e.width))

        foot = tk.Frame(self, bg=th.BG)
        foot.pack(fill="x", pady=(8, 0))
        tk.Label(foot, text="項目をダブルクリックで書きかえ", bg=th.BG,
                 fg=th.INK_SUB, font=F["small"]).pack(side="left")
        th.RoundButton(foot, "全部消す", self.clear_all, kind="danger", bg=th.BG,
                       font=F["small"], padx=14).pack(side="right")

    def set_compact(self, compact):
        """窓が狭いときは説明文を隠して一覧の場所を稼ぐ。

        ページが非表示のあいだ winfo_ismapped() は常に 0 を返すので、
        状態はフラグで持つ（見た目で判定すると毎回 pack し直してしまう）。
        """
        if compact == self._compact:
            return
        self._compact = compact
        if compact:
            self.lbl_hint.pack_forget()
        else:
            self.lbl_hint.pack(side="left", fill="x", expand=True)

    # ---- 表示 ----
    def count_of(self, key):
        if key == "all":
            return len(self.items)
        if key == "todo":
            return sum(1 for i in self.items if not i["state"])
        return sum(1 for i in self.items if i["state"] == key)

    def visible(self):
        if self.filter == "all":
            return list(self.items)
        if self.filter == "todo":
            return [i for i in self.items if not i["state"]]
        return [i for i in self.items if i["state"] == self.filter]

    def render(self):
        for key, _ in CHECK_FILTERS:
            self.chips[key].update_view(self.filter == key, self.count_of(key))
        for w in self.inner.winfo_children():
            w.destroy()

        shown = self.visible()
        if not shown:
            box = tk.Frame(self.inner, bg=th.BG)
            box.pack(fill="x")
            if not self.items:
                icon, msg = "🗒", "まだ項目はありません"
            elif self.filter == "todo":
                icon, msg = "🎉", "やることはありません"
            else:
                icon, msg = "🗒", "この絞り込みに当てはまる項目はありません"
            tk.Label(box, text=icon, bg=th.BG, font=(th.JP, 34)).pack(pady=(30, 6))
            tk.Label(box, text=msg, bg=th.BG, fg=th.INK,
                     font=th.F["cute_b"]).pack()
            if not self.items:
                tk.Label(box, text="上の欄に書いて Enter で追加できます",
                         bg=th.BG, fg=th.INK_SUB,
                         font=th.F["small"]).pack(pady=(4, 0))
        else:
            for item in shown:
                self._row(item)

        done = self.count_of("ok")
        self.lbl_count.configure(
            text="%d / %d 完了" % (done, len(self.items)) if self.items else "")
        self.canvas.yview_moveto(0.0)

    def _row(self, item):
        row = tk.Frame(self.inner, bg=th.CARD, highlightthickness=1,
                       highlightbackground=th.LINE, highlightcolor=th.LINE)
        row.pack(fill="x", padx=2, pady=3)

        marks = tk.Frame(row, bg=th.CARD)
        marks.pack(side="left", padx=(8, 6), pady=7)
        for st in CHECK_STATES:
            b = MarkButton(marks, st, lambda k, it=item: self.toggle(it, k))
            b.set_active(item["state"] == st)
            b.pack(side="left", padx=2)

        struck = item["state"] in ("ok", "ng")
        f = tkfont.Font(font=th.F["ui"])
        if struck:
            f.configure(overstrike=1)
        lbl = tk.Label(row, text=item["text"], bg=th.CARD,
                       fg=th.INK_SUB if struck else th.INK, font=f,
                       anchor="w", justify="left", wraplength=400)
        lbl.pack(side="left", fill="x", expand=True, pady=7)
        lbl.bind("<Double-Button-1>",
                 lambda e, it=item, w=lbl, r=row: self.rename(it, w, r))
        # 窓幅に合わせて折り返し位置を追従させる（印と × の分を引く）
        row.bind("<Configure>", lambda e, w=lbl: w.configure(
            wraplength=max(120, e.width - 150)))

        dele = tk.Label(row, text="×", bg=th.CARD, fg=th.LINE,
                        font=th.F["cute_b"], cursor="hand2", padx=8)
        dele.pack(side="right", pady=7)
        dele.bind("<ButtonRelease-1>", lambda e, it=item: self.remove(it))
        dele.bind("<Enter>", lambda e, w=dele: w.configure(fg=th.RED))
        dele.bind("<Leave>", lambda e, w=dele: w.configure(fg=th.LINE))

    # ---- 操作 ----
    def set_filter(self, key):
        self.filter = key
        self.render()

    def toggle(self, item, key):
        item["state"] = None if item["state"] == key else key
        self.save()
        self.render()

    def add(self):
        text = self.var_new.get().strip()
        if not text:
            return
        self.items.append({"text": text, "state": None})
        self.var_new.set("")
        if self.filter not in ("todo", "all"):
            self.filter = "todo"
        self.save()
        self.render()
        self.entry.focus_set()

    def rename(self, item, lbl, row):
        """別窓を出さずに、その行を入力欄に差し替えて書きかえる。"""
        if getattr(self, "_editing", False):
            return
        self._editing = True
        lbl.pack_forget()
        var = tk.StringVar(value=item["text"])
        ent = th.soft_entry(row, var)
        ent.pack(side="left", fill="x", expand=True, pady=5)
        ent.focus_set()
        ent.icursor("end")
        ent.select_range(0, "end")

        def finish(save_it):
            if not self._editing:
                return
            self._editing = False
            if save_it:
                new = var.get().strip()
                if new and new != item["text"]:
                    item["text"] = new
                    self.save()
            self.render()

        ent.bind("<Return>", lambda e: finish(True))
        ent.bind("<FocusOut>", lambda e: finish(True))
        ent.bind("<Escape>", lambda e: finish(False))

    def remove(self, item):
        if item not in self.items:
            return
        if not self.app.ask_delete(item.get("text") or "この項目", parent=self):
            return
        self.items.remove(item)
        self.save()
        self.render()

    def clear_all(self):
        if not self.items:
            return
        # 確認するかどうかは設定にしたがう（オフなら黙って消す）
        if self.app.cfg.get("confirm_delete", True):
            if not messagebox.askyesno(APP_NAME, "全部の項目を消します。よろしいですか？",
                                       parent=self):
                return
        self.items.clear()      # 共有リストなので中身だけ空にする
        self.save()


class MiniWindow(tk.Toplevel):
    """タイマーだけを出しておく小窓。

    ゲームの横に置いておく用。1本ごとに
      名前 / 残り時間 / 音量 / 音を出すか / 画面中央に大きく出すか
    を直接いじれる。
    """

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.rows = {}
        self.title("ふわふわタイマー（ミニ）")
        self.configure(bg=th.BG)
        self.attributes("-topmost", True)
        self.minsize(240, 130)
        self.geometry(app.cfg.get("mini_geometry") or "300x320")
        try:
            self.iconphoto(False, app._icon)
        except (tk.TclError, AttributeError):
            pass

        bar = tk.Frame(self, bg=th.BG)
        bar.pack(fill="x", padx=8, pady=(8, 4))
        th.RoundButton(bar, "戻る", self.back, kind="soft", bg=th.BG,
                       font=th.F["small"], padx=10).pack(side="right")
        self.tabs = {}
        for key, label in (("timers", "⏰"), ("checklist", "🗒")):
            p = Pill(bar, label, lambda k=key: self.show_page(k), bg=th.BG,
                     padx=10, pady=4)
            p.pack(side="left", padx=(0, 4))
            self.tabs[key] = p
        self.lbl_head = tk.Label(bar, text="", bg=th.BG, fg=th.INK_SUB,
                                 font=th.F["small"], anchor="w")
        self.lbl_head.pack(side="left", padx=(4, 0))

        # ---- タイマーのページ ----
        self.page_timer = tk.Frame(self, bg=th.BG)

        self.add_bar = FlowFrame(self.page_timer, bg=th.BG, gap_x=4, gap_y=4)
        self.add_bar.pack(fill="x", padx=5, pady=(0, 4))
        self.refresh_quick()

        wrap = tk.Frame(self.page_timer, bg=th.BG)
        wrap.pack(fill="both", expand=True, padx=5, pady=(0, 7))
        self.canvas = tk.Canvas(wrap, bg=th.BG, highlightthickness=0, bd=0)
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview,
                           style="Cute.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=th.BG)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win, width=e.width))

        # ---- チェックリストのページ（本体と同じ中身を映す）----
        self.page_check = ChecklistPage(self, app, compact=True)

        self.bind("<MouseWheel>", self._wheel)
        self.protocol("WM_DELETE_WINDOW", self.back)
        self.page = None
        self.show_page(app.cfg.get("mini_page") or "timers")
        self.rebuild()

    def show_page(self, name):
        if name not in ("timers", "checklist"):
            name = "timers"
        self.page = name
        for key, pill in self.tabs.items():
            pill.update_view(key == name)
        self.page_timer.pack_forget()
        self.page_check.pack_forget()
        if name == "checklist":
            self.page_check.pack(fill="both", expand=True, padx=8, pady=(0, 7))
            self.lbl_head.configure(text="")   # 🔊🖥 の凡例はタイマー側だけの話
        else:
            self.page_timer.pack(fill="both", expand=True)
            self.update_view()
        self.app.cfg["mini_page"] = name

    def new_timer(self):
        self.app.open_new_dialog(parent=self)

    def refresh_quick(self):
        """「＋追加」と、設定した「さくっと」ボタン（狭いので先頭4つまで）。"""
        self.add_bar.clear()
        self.add_bar.add(th.RoundButton(self.add_bar, "＋ 追加", self.new_timer,
                                        kind="primary", bg=th.BG,
                                        font=th.F["small"], padx=12), gap_x=6)
        for it in self.app.quick_specs()[:4]:
            self.add_bar.add(th.Chip(
                self.add_bar, it["label"],
                lambda s=it["sec"], t=it["label"]: self.app.quick_add(t, s),
                bg=th.BG, font=th.F["small"]))

    def _wheel(self, e):
        cv = self.page_check.canvas if self.page == "checklist" else self.canvas
        try:
            cv.yview_scroll(int(-e.delta / 120), "units")
        except tk.TclError:
            pass

    # ---- 一覧 ----
    def rebuild(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.rows.clear()
        timers = sorted(self.app.timers,
                        key=lambda x: (x.remaining() <= 0, x.remaining()))
        if not timers:
            tk.Label(self.inner, text="タイマーはありません", bg=th.BG,
                     fg=th.INK_SUB, font=th.F["ui"]).pack(pady=30)
            return
        for t in timers:
            self.rows[t.id] = self._row(t)
        self.update_view()

    def _row(self, t):
        card = tk.Frame(self.inner, bg=th.CARD, highlightthickness=1,
                        highlightbackground=th.LINE, highlightcolor=th.LINE)
        card.pack(fill="x", padx=3, pady=2)
        inner = tk.Frame(card, bg=th.CARD)
        inner.pack(fill="x", padx=7, pady=5)

        top = tk.Frame(inner, bg=th.CARD)
        top.pack(fill="x")
        icon = th.KIND_STYLE.get(t.kind, ("⏰", th.PEACH, ""))[0]
        dele = tk.Label(top, text="×", bg=th.CARD, fg=th.LINE,
                        font=th.F["cute_b"], cursor="hand2", padx=4)
        dele.pack(side="right")
        dele.bind("<ButtonRelease-1>", lambda e, tt=t: self._delete(tt))
        dele.bind("<Enter>", lambda e, w=dele: w.configure(fg=th.RED))
        dele.bind("<Leave>", lambda e, w=dele: w.configure(fg=th.LINE))
        rem = tk.Label(top, text="", bg=th.CARD, fg=th.PINK_DK,
                       font=th.F["num_s"])
        rem.pack(side="right", padx=(0, 4))
        lbl = tk.Label(top, text="%s %s" % (icon, t.label), bg=th.CARD, fg=th.INK,
                       font=th.F["ui_b"], anchor="w", justify="left")
        lbl.pack(side="left", fill="x", expand=True)

        ctl = tk.Frame(inner, bg=th.CARD)
        ctl.pack(fill="x", pady=(4, 0))
        b_sound = Pill(ctl, "🔊", lambda: self._toggle(t, "sound_on"),
                       bg=th.CARD, padx=8, pady=4)
        b_sound.pack(side="left", padx=(0, 3))
        b_center = Pill(ctl, "🖥", lambda: self._toggle(t, "center"),
                        bg=th.CARD, padx=8, pady=4)
        b_center.pack(side="left", padx=(0, 3))
        b_repeat = Pill(ctl, "🔁", lambda tt=t: self._repeat(tt),
                        bg=th.CARD, padx=8, pady=4)
        b_repeat.pack(side="left", padx=(0, 6))

        # 刷り込み待ちなら「次の回へ」、終わったタイマーなら「片づける」
        if t.kind == "imprint" and t.imp_index < t.imp_count:
            if t.done and t.remaining() <= 0:
                Pill(ctl, "✔", lambda tt=t: self.app.imprint_next(tt), bg=th.CARD,
                     padx=8, pady=4).pack(side="left", padx=(0, 6))
        elif t.done and not t.paused and t.remaining() <= 0:
            Pill(ctl, "✔", lambda tt=t: self.app.remove_timer(tt.id), bg=th.CARD,
                 padx=8, pady=4).pack(side="left", padx=(0, 6))

        # %表示を先に確保してから、残りをスライダーに広げる
        # （expand=True を先に pack すると余白を全部持っていってしまう）
        pct = tk.Label(ctl, text="", bg=th.CARD, fg=th.INK_SUB, font=th.F["small"],
                       width=4, anchor="e")
        pct.pack(side="right")
        vol = th.RoundSlider(ctl, value=t.eff_volume(self.app.cfg.get("volume", 0.7)),
                             command=lambda v, tt=t: self._set_volume(tt, v),
                             bg=th.CARD, height=22, track_h=6, knob_r=7)
        vol.pack(side="left", fill="x", expand=True, padx=(0, 4))

        return {"timer": t, "rem": rem, "sound": b_sound, "center": b_center,
                "repeat": b_repeat, "vol": vol, "pct": pct, "label": lbl}

    def _delete(self, t):
        if self.app.ask_delete(t.label or "むめい", parent=self):
            self.app.remove_timer(t.id)   # 中で rebuild まで走る

    def _repeat(self, t):
        RepeatDialog(self.app, t, parent=self)

    def _toggle(self, t, attr):
        setattr(t, attr, not getattr(t, attr))
        self.app.save_timers()
        self.update_view()

    def _set_volume(self, t, v):
        t.volume = max(0.0, min(1.0, float(v)))
        self.app.save_timers()
        self.update_view()

    def update_view(self, now=None):
        now = now or time.time()
        live = 0
        for r in self.rows.values():
            t = r["timer"]
            rem = t.remaining(now)
            if rem > 0 and not t.done:
                live += 1
            r["rem"].configure(
                text=("完了" if (t.done or rem <= 0)
                      else ("一時停止" if t.paused else fmt_dur(rem))),
                fg=th.INK_SUB if (t.done or rem <= 0) else th.PINK_DK)
            r["sound"].update_view(t.sound_on)
            r["center"].update_view(t.center)
            r["repeat"].update_view(t.repeat)
            v = t.eff_volume(self.app.cfg.get("volume", 0.7))
            r["pct"].configure(text="%d%%" % round(v * 100))
        # アイコンだけだと意味が分からないので、ここで凡例も兼ねる
        if self.page != "checklist":
            self.lbl_head.configure(text="%d本　🔊音 🖥中央 🔁くり返し" % live)

    def back(self):
        self.app.close_mini()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = dict(DEFAULT_CONFIG)
        self.cfg.update(load_json(CONFIG_PATH, {}))
        self.db = SpeciesDB(os.path.join(DATA_DIR, "species.json"))
        self.tdb = taming.TamingDB(os.path.join(DATA_DIR, "taming.json"))
        self.notifier = Notifier(self)
        self.timers: list[BreedTimer] = []
        self.cards: dict[str, TimerCard] = {}
        self.popup = None
        self.mini = None
        self.alarm_on = False
        # AFK防止（起動時は必ず止まった状態から。勝手にキーを送らない）
        self.afk_running = False
        self.afk_next = 0.0
        self.afk_count = 0
        self.afk_why = ""
        # マクロ（連射）。起動時は必ず止まった状態から
        self.macro = None
        self.hotkey = None
        self._hotkey_err = ""
        # 起動前に終わっていたタイマーを開いた瞬間に消さないための基準時刻
        self.start_ts = time.time()
        self.clocks = gametime.ClockSet.migrate(self.cfg.get("game_clock"),
                                                self.cfg.get("game_clocks"))
        self.watcher = serverwatch.Watcher(
            self._watch_targets, self._watch_event,
            self.cfg.get("watch_interval", 60))
        self.watch_msg = {}
        self.watcher.start()
        # チェックリストは本体とミニ表示で同じものを見せるので App が持つ
        self.checklist_items = load_checklist()
        self.checklist_pages = []

        self.title(APP_NAME)
        self.geometry(self.cfg.get("geometry", "980x700"))
        self.minsize(380, 300)
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
        self._pad = 18
        head = tk.Frame(self, bg=th.BG)
        head.pack(fill="x", padx=self._pad, pady=(14, 0))

        self.head = head
        self.head_top = top = tk.Frame(head, bg=th.BG)
        top.pack(fill="x")
        tk.Label(top, text="⏰ ふわふわタイマー", bg=th.BG, fg=th.INK,
                 font=F["head"]).pack(side="left")
        # 更新できたかが一目で分かるように、版を出しておく
        tk.Label(top, text=" v%s" % APP_VERSION, bg=th.BG, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left", anchor="s", pady=(0, 4))
        # 窓が狭いときはこのまとまりごと下の行へ移す（_on_resize）。
        # 移動先が head なので、マスターは top ではなく head にしておく
        # （Tk は master かその子孫にしか pack できない）。
        self.head_ctrl = tk.Frame(head, bg=th.BG)
        self.head_ctrl.pack(in_=top, side="right")
        th.RoundButton(self.head_ctrl, "⚙ 設定", self.open_settings, kind="soft",
                       bg=th.BG, font=F["small"]).pack(side="right", padx=(6, 0))
        th.RoundButton(self.head_ctrl, "⬆ 更新", self.open_update, kind="soft",
                       bg=th.BG, font=F["small"]).pack(side="right", padx=6)
        th.RoundButton(self.head_ctrl, "🔔 音を試す", self.test_sound, kind="soft",
                       bg=th.BG, font=F["small"]).pack(side="right", padx=6)
        th.RoundButton(self.head_ctrl, "🗕 ミニ表示", self.open_mini, kind="accent",
                       bg=th.BG, font=F["small"]).pack(side="right", padx=6)
        self.var_top = tk.BooleanVar(value=bool(self.cfg["always_on_top"]))
        tk.Checkbutton(self.head_ctrl, text="最前面", variable=self.var_top,
                       command=self.apply_topmost, bg=th.BG, fg=th.INK_SUB,
                       activebackground=th.BG, activeforeground=th.INK,
                       selectcolor=th.CARD, font=F["small"], bd=0,
                       highlightthickness=0).pack(side="right", padx=6)

        self.lbl_next = tk.Label(head, text="", bg=th.BG, fg=th.INK_SUB,
                                 font=F["cute"], anchor="w")
        self.lbl_next.pack(fill="x", pady=(2, 8))

        # タブが増えたので、窓が狭いときは折り返す
        tabs = FlowFrame(head, bg=th.BG, gap_x=6, gap_y=6)
        tabs.pack(fill="x", pady=(0, 10))
        self.tabs = {}
        for key, label in (("timers", "⏰ タイマー"),
                           ("checklist", "🗒 チェックリスト"),
                           ("afk", "🎮 AFK防止"),
                           ("macro", "🖱 マクロ"),
                           ("gametime", "🌙 ゲーム内時計")):
            self.tabs[key] = tabs.add(
                Pill(tabs, label, lambda k=key: self.show_page(k), bg=th.BG,
                     font=F["cute"]))

        # ---------------- タイマーのページ ----------------
        self.page_timer = tk.Frame(self, bg=th.BG)

        self.quick = FlowFrame(self.page_timer, bg=th.BG, gap_x=6)
        self.quick.pack(fill="x", padx=18, pady=(0, 10))
        self.refresh_quick()

        # 一覧
        wrap = tk.Frame(self.page_timer, bg=th.BG)
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

        # ---------------- チェックリストのページ ----------------
        self.page_check = ChecklistPage(self, self)

        # ---------------- AFK防止のページ ----------------
        self.page_afk = AfkPage(self, self)

        # ---------------- マクロのページ ----------------
        self.page_macro = MacroPage(self, self)

        # ---------------- ゲーム内時計のページ ----------------
        self.page_gametime = GameTimePage(self, self)
        self.apply_hotkey()

        self.show_page(self.cfg.get("page") or "timers")

        self._compact = None
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, e):
        """窓が狭いときはヘッダーのボタン類をタイトルの下の行へ逃がす。"""
        if e.widget is not self:
            return
        compact = e.width < 620
        if compact == self._compact:
            return
        self._compact = compact

        self.head_ctrl.pack_forget()
        if compact:
            self.head_ctrl.pack(in_=self.head, fill="x", pady=(6, 0),
                                before=self.lbl_next)
        else:
            self.head_ctrl.pack(in_=self.head_top, side="right")

        # 狭いときは余白と説明文を削って一覧の場所を稼ぐ
        self._pad = 10 if compact else 18
        self.head.pack_configure(padx=self._pad, pady=(8 if compact else 14, 0))
        self.page_check.set_compact(compact)
        if self.page == "checklist":
            self.page_check.pack_configure(padx=self._pad)

    # ---------------- ミニ表示 ----------------
    def open_mini(self):
        """タイマーだけの小窓を出して、本体はしまう。"""
        if self.mini is not None and self.mini.winfo_exists():
            self.mini.deiconify()
            self.mini.lift()
            return
        self.cfg["geometry"] = self.geometry()
        self.mini = MiniWindow(self)
        self.withdraw()

    def close_mini(self):
        """小窓を閉じて本体に戻る。"""
        if self.mini is not None and self.mini.winfo_exists():
            self.cfg["mini_geometry"] = self.mini.geometry()
            self.mini.destroy()
        self.mini = None
        self.deiconify()
        self.lift()

    def show_page(self, name):
        """⏰タイマー / 🗒チェックリスト / 🎮AFK防止 / 🖱マクロ の切り替え。"""
        if name not in ("timers", "checklist", "afk", "macro", "gametime"):
            name = "timers"
        self.page = name
        for key, pill in self.tabs.items():
            pill.update_view(key == name)
        self.page_timer.pack_forget()
        self.page_check.pack_forget()
        self.page_afk.pack_forget()
        self.page_macro.pack_forget()
        self.page_gametime.pack_forget()
        if name == "checklist":
            self.page_check.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        elif name == "afk":
            self.page_afk.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        elif name == "macro":
            self.page_macro.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        elif name == "gametime":
            self.page_gametime.pack(fill="both", expand=True, padx=12,
                                    pady=(0, 12))
        else:
            self.page_timer.pack(fill="both", expand=True)
        self.cfg["page"] = name

    def _on_wheel(self, e):
        page = getattr(self, "page", "timers")
        if page in ("afk", "macro"):
            return   # スクロールする一覧が無いページ
        if page == "gametime":
            cv = self.page_gametime.canvas
        else:
            cv = self.page_check.canvas if page == "checklist" else self.canvas
        try:
            cv.yview_scroll(int(-e.delta / 120), "units")
        except tk.TclError:
            pass

    # ---------------- タイマー ----------------
    def quick_specs(self):
        """設定された「さくっと」ボタンの一覧を掃除して返す。"""
        out = []
        for it in (self.cfg.get("quick_buttons") or []):
            try:
                sec = float(it.get("sec") or 0)
            except (TypeError, ValueError):
                continue
            if sec <= 0:
                continue
            out.append({"label": str(it.get("label") or fmt_dur(sec)), "sec": sec})
        return out or list(DEFAULT_CONFIG["quick_buttons"])

    def quick_add(self, label, sec):
        self.add_timer(BreedTimer("custom", label + "タイマー", sec))

    def refresh_quick(self):
        """設定を変えたあとに「さくっと」の並びを作り直す。"""
        self.quick.clear()
        F = self.F
        self.quick.add(th.RoundButton(self.quick, "＋ 新しいタイマー",
                                      self.open_new_dialog, kind="primary",
                                      bg=th.BG, font=F["cute"]), gap_x=12)
        self.quick.add(tk.Label(self.quick, text="さくっと:", bg=th.BG,
                                fg=th.INK_SUB, font=F["small"]))
        for it in self.quick_specs():
            self.quick.add(th.Chip(
                self.quick, it["label"],
                lambda s=it["sec"], t=it["label"]: self.quick_add(t, s),
                bg=th.BG, font=F["small"]))
        if self.mini is not None and self.mini.winfo_exists():
            self.mini.refresh_quick()

    def ask_delete(self, name, parent=None):
        """✕ を押したときの確認。設定でオフなら何も聞かずに True。"""
        if not self.cfg.get("confirm_delete", True):
            return True
        return messagebox.askyesno(APP_NAME, "「%s」を消しますか？" % name,
                                   parent=parent or self)

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

    # ---- 終わったタイマーの自動そうじ ----
    def clear_at(self, t: BreedTimer):
        """このタイマーが自動で消える時刻。消えないものは None。"""
        if not self.cfg.get("auto_clear_done", True):
            return None
        if not t.done or t.paused or t.repeat:
            return None
        if t.kind == "imprint" and t.imp_index < t.imp_count:
            return None   # 「✔ できた」待ちなので残す
        span = max(10, int(self.cfg.get("auto_clear_sec", 600) or 600))
        # 起動前に終わっていた分は、起動から数えて猶予をあげる
        return max(t.end_ts, self.start_ts) + span

    def _auto_clear(self, now):
        due = [t for t in self.timers
               if (at := self.clear_at(t)) is not None and now >= at]
        if not due:
            return
        gone = {t.id for t in due}
        self.timers = [t for t in self.timers if t.id not in gone]
        self.rebuild_list()
        self.save_timers()

    def rebuild_list(self):
        for c in self.cards.values():
            c.destroy()
        self.cards.clear()
        self.empty.pack_forget()
        if not self.timers:
            self.empty.pack(fill="x")
        else:
            for t in sorted(self.timers,
                            key=lambda x: (x.remaining() <= 0, x.remaining())):
                card = TimerCard(self.list_frame, self, t)
                card.pack(fill="x", pady=1)
                self.cards[t.id] = card
        # 空になったときも忘れずに（ここを早期 return の後ろに置くと更新されない）
        if self.mini is not None and self.mini.winfo_exists():
            self.mini.rebuild()

    def save_timers(self):
        save_json(TIMERS_PATH, [t.to_dict() for t in self.timers])

    def save_checklist(self):
        """保存して、開いているチェックリスト画面をぜんぶ描き直す。"""
        save_json(CHECKLIST_PATH, self.checklist_items)
        self.checklist_pages = [p for p in self.checklist_pages if p.winfo_exists()]
        for p in self.checklist_pages:
            p.render()

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
                                   "あと %s" % fmt_dur(rem), urgent=False,
                                   timer=t)
            ms = t.milestone_ts
            if ms is not None and not t.milestone_done and now >= ms:
                t.milestone_done = True
                changed = True
                self.notifier.fire("%s — %s" % (t.label, t.milestone_text),
                                   t.species, urgent=False, timer=t)
            if rem <= 0 and not t.done:
                t.done = True
                changed = True
                self._on_complete(t)
        if changed:
            self.save_timers()
            self.rebuild_list()
        self._auto_clear(now)
        for c in self.cards.values():
            c.update_view(now)
        if self.mini is not None and self.mini.winfo_exists():
            self.mini.update_view(now)
        self._update_head(now)
        self._afk_tick(now)
        self._macro_tick()
        # 過ぎた定期再起動のぶんを差し引く（画面を開いていなくても効かせる）
        for _c in self.clocks.clocks.values():
            _c.apply_restarts(now)
        if getattr(self, "page", "") == "gametime":
            self.page_gametime.update_view(now)
        self.after(250, self._tick)

    # ---------------- マクロ（連射） ----------------
    def macro_running(self):
        return self.macro is not None and self.macro.is_alive()

    def _macro_cfg(self):
        """連射スレッドが毎回読む設定のスナップショット。"""
        c = self.cfg
        return {
            "action": c.get("macro_action") or macro.DEFAULT_ACTION,
            "key_vk": c.get("macro_key_vk") or 0,
            "key_scan": c.get("macro_key_scan") or 0,
            "interval_ms": c.get("macro_interval_ms", 100),
            "hold_ms": c.get("macro_hold_ms", 20),
            "limit": c.get("macro_limit", 0),
            "target": c.get("macro_target") or "",
            "only_target": c.get("macro_only_target", True),
        }

    def toggle_macro(self):
        """入切。ホットキーのスレッドから呼ばれてもいいように Tk は触らない。"""
        if self.macro_running():
            self.macro.stop()
            self.macro = None
        else:
            if (self.cfg.get("macro_action") == "key"
                    and not self.cfg.get("macro_key_vk")):
                return   # 送るキーが決まっていないので始めない
            self.macro = macro.Runner(self._macro_cfg)
            self.macro.start()

    def stop_macro(self):
        if self.macro is not None:
            self.macro.stop()
            self.macro = None

    def apply_hotkey(self):
        """設定に合わせてグローバルホットキーを登録し直す。"""
        if self.hotkey is not None:
            self.hotkey.stop()
            self.hotkey = None
        self._hotkey_err = ""
        if not self.cfg.get("macro_hotkey_on", True):
            return
        hk = macro.Hotkey(self.cfg.get("macro_hotkey_mods", macro.MOD_CONTROL),
                          self.cfg.get("macro_hotkey_vk", 0x52),
                          self.toggle_macro)
        hk.start()
        hk.ready.wait(1.0)
        if not hk.ok:
            self._hotkey_err = hk.error or "登録できませんでした"
            self.hotkey = None
        else:
            self.hotkey = hk

    def hotkey_status(self):
        name = macro.hotkey_name(self.cfg.get("macro_hotkey_mods", macro.MOD_CONTROL),
                                 self.cfg.get("macro_hotkey_vk", 0x52))
        if not self.cfg.get("macro_hotkey_on", True):
            return "ショートカットは使いません（この画面のボタンで入切します）"
        if self._hotkey_err:
            return "⚠ %s が使えません（%s）。別の組み合わせにしてください" % (
                name, self._hotkey_err)
        return ("%s でどこからでも入切できます。"
                "登録中はほかのアプリでもこの組み合わせは効かなくなります" % name)

    def _macro_tick(self):
        # 撃ち終わったスレッドは残しておく（回数の表示に使うため）。
        # macro_running() が is_alive() を見ているので、止まった扱いになる。
        if getattr(self, "page", "") == "macro":
            self.page_macro.update_view()

    def _afk_tick(self, now):
        """AFK防止: 時間が来たらキーを送る。"""
        if self.afk_running and now >= self.afk_next:
            sent, why = afk.send(self.cfg.get("afk_mode") or afk.DEFAULT_MODE,
                                 self.cfg.get("afk_target") or "",
                                 self.cfg.get("afk_key") or afk.DEFAULT_KEY,
                                 self.cfg.get("afk_times", 1),
                                 self.cfg.get("afk_gap_ms", 60))
            self.afk_why = why
            if sent:
                self.afk_count += 1
                self.afk_next = now + max(5, int(self.cfg.get("afk_interval", 120)))
            else:
                self.afk_next = now + 2   # 送れる状態になるまで様子を見る
        if getattr(self, "page", "") == "afk":
            self.page_afk.update_view(now)

    def _on_complete(self, t: BreedTimer):
        if t.kind == "imprint":
            self.notifier.fire(
                "💗 刷り込みの時間! — %s" % t.label,
                "%s  %d/%d回目 (+%.1f%%)" % (t.species, t.imp_index + 1,
                                             t.imp_count, t.imp_per),
                sound_spec=t.sound or None, timer=t)
            return
        msg = {"hatch": "🥚 卵が孵りました", "gestation": "🌸 出産の時間です",
               "mature": "🌱 成長が完了しました", "matingcd": "💞 再交配できます",
               "custom": "⏰ 時間になりました"}.get(t.kind, "時間になりました")
        self.notifier.fire("%s — %s" % (msg, t.label), t.species or t.note or "",
                           sound_spec=t.sound or None, timer=t)
        if t.chain and self.cfg.get("auto_chain"):
            self._spawn_chain(t)
        if t.repeat:
            t.repeat_done += 1
            interval = t.repeat_interval()
            if t.repeat_count > 0 and t.repeat_done >= t.repeat_count:
                t.repeat = False   # 指定回数ぶん鳴ったので終わり
                t.note = t.note or "くり返し %d回 おわり 🎉" % t.repeat_done
            elif interval > 0:
                t.total = interval
                t.end_ts = time.time() + interval
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

    def make_timers(self, sp, label, c, kinds, offset=0.0, offset_kinds=None):
        """種族と計算結果からタイマー群を作る。

        offset秒だけ経過済みとして扱う。offset_kinds を渡すと、そこに入っている
        種類にだけ offset を適用する（成熟度から作るときは成長と刷り込みだけ）。
        """
        out, now = [], time.time()

        def off(kind):
            if offset <= 0:
                return 0.0
            if offset_kinds is None or kind in offset_kinds:
                return offset
            return 0.0

        for kind, total in (("hatch", c["hatch"]), ("gestation", c["gestation"])):
            if kind in kinds and total > 0:
                t = BreedTimer(kind, label, total, sp["name"])
                t.end_ts = now + max(0.0, total - off(kind))
                t.chain = True
                out.append(t)
        if "mature" in kinds and c["mature"] > 0:
            o = off("mature")
            t = BreedTimer("mature", label, c["mature"], sp["name"])
            t.end_ts = now + max(0.0, c["mature"] - o)
            t.milestone_text = "成長10% おいていけます"
            if o < c["mature"] * 0.10:
                t.milestone_frac = 0.10
            else:
                t.milestone_done = True
            out.append(t)
        if "imprint" in kinds and c["imprint_count"] > 0:
            interval = c["imprint_interval"]
            o = off("imprint")
            # 途中から作るときは、もう済んでいる回数を数えて次の1回までを出す
            done = min(int(o // interval) if interval > 0 else 0, c["imprint_count"])
            if done < c["imprint_count"]:
                to_next = interval - (o % interval) if interval > 0 else 0.0
                t = BreedTimer("imprint", label, interval, sp["name"])
                t.end_ts = now + max(0.0, to_next)
                t.imp_index = done
                t.imp_count = c["imprint_count"]
                t.imp_per = c["imprint_per"]
                t.mature_end = now + max(0.0, c["mature"] - off("mature"))
                out.append(t)
        if "matingcd" in kinds and c["cd_hi"] > 0:
            t = BreedTimer("matingcd", label, c["cd_lo"], sp["name"])
            t.end_ts = now + max(0.0, c["cd_lo"] - off("matingcd"))
            t.note = "最短 %s / 最長 %s のあいだでランダム" % (
                fmt_dur(c["cd_lo"]), fmt_dur(c["cd_hi"]))
            out.append(t)
        return out

    def _watch_targets(self):
        """見張る相手の一覧。アドレスを入れたマップだけ。"""
        out = []
        for name in self.clocks.order:
            c = self.clocks.clocks.get(name)
            if c is not None and c.address:
                out.append((name, c.address))
        return out

    def _watch_event(self, name, kind, value):
        """見張りスレッドからの知らせ。Tkは触らず、時計だけ動かす。"""
        c = self.clocks.clocks.get(name)
        if c is None:
            return
        if kind == "hold":
            # 落ちている間はゲーム内時間も進まないので、その分だけ止める
            c.hold(value)
        elif kind == "day":
            _old, _new, prev_at = value
            msg = c.on_day_changed(prev_at)
            if msg:
                self.watch_msg[name] = msg

    def save_clocks(self):
        self.cfg["game_clocks"] = self.clocks.to_dict()

    def add_game_time_timer(self, label, seconds, note=""):
        """ゲーム内時計から「夜になったら」タイマーを作る。"""
        t = BreedTimer("custom", label, seconds)
        t.note = note
        self.add_timer(t)
        return t

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

    def show_popup(self, title, body, urgent=True, sound_spec=None,
                   center=False, volume=None, sound_on=True):
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.destroy()
        p = tk.Toplevel(self)
        self.popup = p
        p.title(title)
        p.configure(bg=th.BG)
        p.attributes("-topmost", True)
        p.resizable(False, False)
        # 中央表示は大きめに出す（メインモニターのまんなか）
        w, h = (560, 260) if center else (420, 210)
        if center:
            x = (p.winfo_screenwidth() - w) // 2
            y = (p.winfo_screenheight() - h) // 2
        else:
            x, y = p.winfo_screenwidth() - w - 36, 56
        p.geometry("%dx%d+%d+%d" % (w, h, x, y))
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

        # 自分から消えるまでの残りを細いバーで見せる（0秒設定なら出さない）
        auto = self.cfg.get("popup_close_done" if urgent else "popup_close_prewarn")
        try:
            auto = float(auto or 0)
        except (TypeError, ValueError):
            auto = 0.0
        p.protocol("WM_DELETE_WINDOW", lambda: self._close_popup(p))
        if urgent and self.cfg.get("repeat_alarm") and sound_on:
            self.alarm_on = True
            self._repeat_alarm(p, sound_spec, 0, volume)
        if auto > 0:
            bar = th.RoundProgress(b, bg=th.CARD,
                                   color=th.PINK if urgent else th.LAV, height=4)
            bar.pack(fill="x", pady=(10, 0))
            self._popup_countdown(p, bar, time.time() + auto, auto)
        else:
            p.after(180000, lambda: self._close_popup(p))   # 万一の保険

    def _popup_countdown(self, p, bar, until, span):
        """ポップアップが自分で閉じるまでのカウントダウン。"""
        if not p.winfo_exists():
            return
        left = until - time.time()
        if left <= 0:
            self._close_popup(p)
            return
        try:
            bar.set(max(0.0, min(1.0, left / span)))
        except tk.TclError:
            return
        p.after(100, lambda: self._popup_countdown(p, bar, until, span))

    def _repeat_alarm(self, p, sound_spec, n, volume=None):
        if not p.winfo_exists() or not self.alarm_on or n > 40:
            return
        if n > 0:
            vol = self.cfg.get("volume", 0.7) if volume is None else volume
            snd.play_async(sound_spec or self.cfg["sound_done"], vol, SOUND_CACHE)
        p.after(6000, lambda: self._repeat_alarm(p, sound_spec, n + 1, volume))

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
    def open_new_dialog(self, parent=None):
        """parent を渡すとそのウィンドウに紐づく（ミニ表示から開くとき用）。"""
        NewTimerDialog(self, parent=parent)

    def open_settings(self):
        SettingsDialog(self)

    def open_update(self):
        UpdateDialog(self)

    def apply_topmost(self):
        self.cfg["always_on_top"] = bool(self.var_top.get())
        self.attributes("-topmost", self.cfg["always_on_top"])
        self.save_cfg()

    def save_cfg(self):
        self.cfg["game_clocks"] = self.clocks.to_dict()
        try:
            self.cfg["geometry"] = self.winfo_geometry()
        except Exception:
            pass
        save_json(CONFIG_PATH, self.cfg)

    def on_close(self):
        if self.mini is not None and self.mini.winfo_exists():
            self.cfg["mini_geometry"] = self.mini.geometry()
        self.save_cfg()
        self.save_timers()
        snd.stop()
        self.stop_macro()          # 連射を止め忘れて暴走させない
        self.watcher.stop()
        if self.hotkey is not None:
            self.hotkey.stop()
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
        th.RoundButton(btns, "✕", self.on_delete, kind="danger",
                       bg=th.CARD, font=F["small"], padx=10, pady=5).pack(side="right",
                                                                         padx=2)
        self.btn_repeat = th.RoundButton(
            btns, "🔁", self.edit_repeat, kind="accent" if t.repeat else "ghost",
            bg=th.CARD, font=F["small"], padx=11, pady=5)
        self.btn_repeat.pack(side="right", padx=2)
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
        elif t.done and not t.paused and t.remaining() <= 0:
            # 終わったタイマーは「できた」で片づける（自動で消えるのを待たなくていい）
            th.RoundButton(btns, "✔ できた", self.on_ack, kind="mint", bg=th.CARD,
                           font=F["small"], padx=12, pady=5).pack(side="right", padx=2)

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

    def on_delete(self):
        if self.app.ask_delete(self.t.label or "むめい"):
            self.app.remove_timer(self.t.id)

    def on_ack(self):
        """「できた」= 確認したので片づける。終わったものなので確認は挟まない。"""
        self.app.remove_timer(self.t.id)

    def edit_repeat(self):
        RepeatDialog(self.app, self.t, parent=self.winfo_toplevel())

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
            text = "おわりました" if over < 1 else "経過"
            at = self.app.clear_at(t)
            if at is not None:
                text += " ・あと %s で消えます" % fmt_dur(max(0.0, at - now))
            self.lbl_eta.config(text=text)
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
            info = t.repeat_text()
        elif t.repeat_done:
            info = "くり返し %d回 おわり" % t.repeat_done
        self.lbl_info.config(text=info)

        if t.note and not self._note_shown:
            self.lbl_note.pack(fill="x", pady=(6, 0))
            self._note_shown = True
        elif not t.note and self._note_shown:
            self.lbl_note.pack_forget()
            self._note_shown = False
        self.lbl_note.config(text=t.note)


# ---------------------------------------------------------------- くり返し
class RepeatPanel(tk.Frame):
    """くり返しの設定（入／回数／間隔）。作成画面とカードの両方で使う。"""

    def __init__(self, master, app, bg=th.CARD, repeat=False, count=0, every=0.0,
                 on_change=None):
        super().__init__(master, bg=bg)
        self.app = app
        self.bg = bg
        self.on_change = on_change
        F = app.F

        self.v_on = tk.BooleanVar(value=bool(repeat))
        self._check(self, "鳴ったあとくり返す 🔁", self.v_on,
                    self._toggled).pack(anchor="w")

        self.box = tk.Frame(self, bg=bg)

        r1 = tk.Frame(self.box, bg=bg)
        r1.pack(anchor="w", pady=(2, 0))
        self.v_times = tk.StringVar(value="forever" if not count else "n")
        self._radio(r1, "ずっと", self.v_times, "forever").pack(side="left")
        self._radio(r1, "", self.v_times, "n").pack(side="left", padx=(14, 0))
        self.v_n = tk.StringVar(value=str(count or 5))
        th.soft_entry(r1, self.v_n, width=4).pack(side="left", ipady=2)
        tk.Label(r1, text=" 回まで", bg=bg, fg=th.INK, font=F["cute"]).pack(side="left")

        r2 = tk.Frame(self.box, bg=bg)
        r2.pack(anchor="w", pady=(2, 0))
        self.v_every = tk.StringVar(value="same" if not every else "custom")
        self._radio(r2, "同じ長さ", self.v_every, "same").pack(side="left")
        self._radio(r2, "", self.v_every, "custom").pack(side="left", padx=(14, 0))
        self.v_int = tk.StringVar(value=fmt_dur(every) if every else "10:00")
        th.soft_entry(r2, self.v_int, width=8).pack(side="left", ipady=2)
        tk.Label(r2, text=" ごと", bg=bg, fg=th.INK, font=F["cute"]).pack(side="left")
        tk.Label(self.box, text="   間隔は 1:30 / 25m / 90（=90分）のように書けます",
                 bg=bg, fg=th.INK_SUB, font=F["small"]).pack(anchor="w")

        self._toggled()

    def _check(self, parent, text, var, cmd=None):
        return tk.Checkbutton(parent, text=text, variable=var, command=cmd,
                              bg=self.bg, fg=th.INK, activebackground=self.bg,
                              activeforeground=th.INK, selectcolor=th.FIELD,
                              font=self.app.F["cute"], bd=0, highlightthickness=0,
                              anchor="w")

    def _radio(self, parent, text, var, value):
        return tk.Radiobutton(parent, text=text, variable=var, value=value,
                              bg=self.bg, fg=th.INK, activebackground=self.bg,
                              activeforeground=th.INK, selectcolor=th.FIELD,
                              font=self.app.F["cute"], bd=0, highlightthickness=0,
                              anchor="w")

    def _toggled(self):
        if self.v_on.get():
            self.box.pack(anchor="w", padx=22, pady=(2, 0))
        else:
            self.box.pack_forget()
        if self.on_change:
            self.on_change()

    def read(self):
        """(repeat, count, every, エラー文) を返す。"""
        if not self.v_on.get():
            return False, 0, 0.0, None
        count = 0
        if self.v_times.get() == "n":
            try:
                count = int(float(self.v_n.get()))
            except ValueError:
                return None, 0, 0.0, "くり返す回数は数字で入れてください"
            if count < 1:
                return None, 0, 0.0, "くり返す回数は1以上にしてください"
        every = 0.0
        if self.v_every.get() == "custom":
            sec = parse_duration(self.v_int.get())
            if sec is None or sec <= 0:
                return None, 0, 0.0, "くり返しの間隔が読めません（例 10:00）"
            every = sec
        return True, count, every, None


class RepeatDialog(tk.Toplevel):
    """作ったあとのタイマーのくり返しを変える小さい窓。"""

    def __init__(self, app, timer, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.t = timer
        self.title("くり返しの設定")
        self.configure(bg=th.BG)
        self.geometry("400x300")
        self.transient(parent or app)
        self.attributes("-topmost", True)

        card = th.Card(self, bg=th.BG)
        card.pack(fill="both", expand=True, padx=10, pady=10)
        b = card.body
        tk.Label(b, text="🔁 %s" % (timer.label or "むめい"), bg=th.CARD, fg=th.INK,
                 font=app.F["cute_b"], anchor="w").pack(fill="x", pady=(0, 8))
        self.panel = RepeatPanel(b, app, repeat=timer.repeat,
                                 count=timer.repeat_count, every=timer.repeat_every)
        self.panel.pack(fill="x")
        if timer.repeat_done:
            tk.Label(b, text="これまで %d回 鳴りました" % timer.repeat_done,
                     bg=th.CARD, fg=th.INK_SUB, font=app.F["small"],
                     anchor="w").pack(fill="x", pady=(8, 0))

        self.lbl_err = tk.Label(b, text="", bg=th.CARD, fg=th.PINK_DK,
                                font=app.F["small"], anchor="w", justify="left",
                                wraplength=340)
        self.lbl_err.pack(side="bottom", fill="x")
        btm = tk.Frame(b, bg=th.CARD)
        btm.pack(side="bottom", fill="x", pady=(12, 0))
        th.RoundButton(btm, "決定", self.save, kind="primary", bg=th.CARD,
                       font=app.F["cute_b"], padx=24).pack(side="right")
        th.RoundButton(btm, "やめる", self.destroy, kind="soft", bg=th.CARD,
                       font=app.F["cute"]).pack(side="right", padx=8)
        th.RoundButton(btm, "回数リセット", self.reset, kind="ghost", bg=th.CARD,
                       font=app.F["small"]).pack(side="left")

    def reset(self):
        self.t.repeat_done = 0
        self.app.save_timers()
        self.app.rebuild_list()

    def save(self):
        rep, count, every, err = self.panel.read()
        if err:
            self.lbl_err.config(text="⚠ " + err)
            return
        self.t.repeat = rep
        self.t.repeat_count = count
        self.t.repeat_every = every
        self.app.save_timers()
        self.app.rebuild_list()
        self.destroy()


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
    def __init__(self, app: App, parent=None):
        super().__init__(app)
        self.app = app
        self.F = app.F
        self.sp = None
        self.calc = None
        self.title("新しいタイマー")
        self.configure(bg=th.BG)
        # くり返しの欄をひらいても「つくる」が隠れない高さ
        self.geometry("800x750")
        self.minsize(700, 620)
        # 本体をしまっているときは、出どころのウィンドウに紐づける
        self.transient(parent if parent is not None else app)
        self.attributes("-topmost", bool(app.cfg["always_on_top"]))

        sw = FlowFrame(self, bg=th.BG, gap_x=8, gap_y=6)
        sw.pack(fill="x", padx=18, pady=(16, 8))
        self.holder = tk.Frame(self, bg=th.BG)
        self.holder.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.tab_btns, self.tab_pages = {}, {}
        for key, label in (("free", "⏰ 自由タイマー"), ("ark", "🦖 ARKの恐竜から"),
                           ("tame", "🍖 テイム")):
            self.tab_btns[key] = sw.add(th.RoundButton(
                sw, label, lambda k=key: self.switch(k), kind="soft", bg=th.BG,
                font=self.F["cute"]))
            self.tab_pages[key] = th.Card(self.holder, bg=th.BG)
        self._build_free(self.tab_pages["free"].body)
        self._build_ark(self.tab_pages["ark"].body)
        self._build_tame(self.tab_pages["tame"].body)
        self.switch("free")

    def switch(self, which):
        for card in self.tab_pages.values():
            card.pack_forget()
        self.tab_pages[which].pack(fill="both", expand=True)
        for key, b in self.tab_btns.items():
            on = key == which
            b.fill = th.PINK if on else th.BG_SOFT
            b.itemconfigure(b.shape, fill=b.fill)
            b.itemconfigure(b.label, fill="#FFFFFF" if on else th.INK)
        if which == "ark":
            self.refresh_list()
        elif which == "tame":
            self.tame_refresh_list()

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

        self.f_repeat = RepeatPanel(f, self.app)
        self.f_repeat.pack(fill="x")

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

    def _warn(self, label, text):
        """ダイアログを出さずに、その場に赤字で出す。"""
        label.config(text="⚠ " + text, fg=th.PINK_DK)

    def create_free(self):
        sec, err = self._free_seconds()
        if err:
            self._warn(self.f_prev, err)
            return
        rep, count, every, rerr = self.f_repeat.read()
        if rerr:
            self._warn(self.f_prev, rerr)
            return
        t = BreedTimer("custom", self.f_label.get().strip() or "タイマー", sec)
        t.repeat = rep
        t.repeat_count = count
        t.repeat_every = every
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

        # 幅は中の部品（計算結果ラベルの width=40 など）にまかせる。
        # pack_propagate(False) で高さを潰すとカード全体が縮んでしまう。
        right = tk.Frame(f, bg=th.CARD)
        right.pack(side="right", fill="y", padx=(14, 0))
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
        rowp = tk.Frame(right, bg=th.CARD)
        rowp.pack(anchor="w", fill="x")
        self._radio(rowp, "成熟度", self.var_start, "mature").pack(side="left")
        self.var_pct = tk.StringVar(value="0")
        th.soft_entry(rowp, self.var_pct, width=6).pack(side="left", padx=4, ipady=3)
        tk.Label(rowp, text="% から", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")

        rowl = tk.Frame(right, bg=th.CARD)
        rowl.pack(anchor="w", fill="x")
        self._radio(rowl, "残り時間", self.var_start, "left").pack(side="left")
        self.var_left = tk.StringVar()
        th.soft_entry(rowl, self.var_left, width=9).pack(side="left", padx=4, ipady=3)
        tk.Label(rowl, text=" から", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")

        self.lbl_start = tk.Label(right, text="", bg=th.CARD, fg=th.PINK_DK,
                                  font=F["small"], anchor="w", justify="left",
                                  wraplength=320)
        self.lbl_start.pack(fill="x", pady=(2, 0))
        for v in (self.var_start, self.var_pct):
            v.trace_add("write", lambda *a: self._start_preview())

        btm = tk.Frame(right, bg=th.CARD)
        btm.pack(side="bottom", fill="x", pady=(12, 0))
        self.ark_err = tk.Label(right, text="", bg=th.CARD, fg=th.PINK_DK,
                                font=F["small"], anchor="w", justify="left",
                                wraplength=320)
        self.ark_err.pack(side="bottom", fill="x")
        th.RoundButton(btm, "つくる", self.create_ark, kind="primary", bg=th.CARD,
                       font=F["cute_b"], padx=26).pack(side="right")
        th.RoundButton(btm, "やめる", self.destroy, kind="soft", bg=th.CARD,
                       font=F["cute"]).pack(side="right", padx=8)

    def _pct(self):
        """成熟度の入力を 0.0〜1.0 で返す。読めなければ None。"""
        try:
            v = float((self.var_pct.get() or "0").strip().rstrip("%"))
        except ValueError:
            return None
        if not 0 <= v <= 100:
            return None
        return v / 100.0

    def _start_preview(self):
        """「成熟度◯%から」だと何がどうなるかを出す。"""
        if not hasattr(self, "lbl_start"):
            return
        mode = self.var_start.get()
        if mode != "mature" or not self.calc:
            self.lbl_start.config(
                text="   例: 1:23:45 / 25m / 90（=90分）" if mode == "left" else "",
                fg=th.INK_SUB)
            return
        p = self._pct()
        if p is None:
            self.lbl_start.config(text="⚠ 成熟度は 0〜100 の数字で", fg=th.PINK_DK)
            return
        c = self.calc
        elapsed = c["mature"] * p
        left = max(0.0, c["mature"] - elapsed)
        lines = ["→ 成体まで あと %s" % fmt_dur(left)]
        if c["imprint_count"]:
            interval = c["imprint_interval"]
            done = min(int(elapsed // interval), c["imprint_count"])
            if done >= c["imprint_count"]:
                lines.append("   刷り込みはもう終わっています")
            else:
                lines.append("   刷り込みは %d/%d回目まで済み・次まで %s" % (
                    done, c["imprint_count"],
                    fmt_dur(interval - (elapsed % interval))))
        if p > 0:
            # もう生まれているので孵化・妊娠は外し、成長と刷り込みを選んでおく
            self.kv["hatch"].set(False)
            self.kv["gestation"].set(False)
            if not any(self.kv[k].get() for k in ("mature", "imprint", "matingcd")):
                self.kv["mature"].set(True)
                self.kv["imprint"].set(True)
            lines.append("   （孵化・妊娠は作りません）")
        self.lbl_start.config(text="\n".join(lines), fg=th.PINK_DK)

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
        else:
            # 見つからなかったときに前の恐竜が居座らないようにする
            self.sp = None
            self.calc = None
            self.lbl_calc.config(text="その名前の恐竜は見つかりません")
            self.lbl_start.config(text="")

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
        self._start_preview()

    # ------------------------------------------------ テイム
    def _build_tame(self, f):
        F = self.F
        left = tk.Frame(f, bg=th.CARD)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="テイムする恐竜（日本語でも英語でも）", bg=th.CARD,
                 fg=th.INK_SUB, font=F["small"]).pack(anchor="w")
        self.tm_q = tk.StringVar()
        ent = th.soft_entry(left, self.tm_q, font=F["cute"])
        ent.pack(fill="x", ipady=5, pady=(2, 8))
        ent.bind("<KeyRelease>", lambda e: self.tame_refresh_list())
        self.tm_list = tk.Listbox(left, bg=th.FIELD, fg=th.INK,
                                  selectbackground=th.PINK,
                                  selectforeground="#FFFFFF", borderwidth=0,
                                  highlightthickness=0, font=F["ui"],
                                  activestyle="none")
        self.tm_list.pack(fill="both", expand=True)
        self.tm_list.bind("<<ListboxSelect>>", lambda e: self.tame_select())

        right = tk.Frame(f, bg=th.CARD)
        right.pack(side="right", fill="y", padx=(14, 0))

        r1 = tk.Frame(right, bg=th.CARD)
        r1.pack(fill="x")
        tk.Label(r1, text="レベル", bg=th.CARD, fg=th.INK, font=F["cute"],
                 width=8, anchor="w").pack(side="left")
        self.tm_level = tk.StringVar(value="150")
        th.soft_entry(r1, self.tm_level, width=7).pack(side="left", ipady=3)
        for lv in (5, 30, 75, 105, 150):
            th.Chip(r1, str(lv), lambda v=lv: self.tm_level.set(str(v)),
                    bg=th.CARD, font=F["small"]).pack(side="left", padx=2)

        tk.Label(right, text="なにで餌付けする？", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(anchor="w", pady=(10, 2))
        self.tm_food = tk.StringVar()
        self.tm_cb = ttk.Combobox(right, textvariable=self.tm_food, state="readonly",
                                  width=34, style="Cute.TCombobox", font=F["ui"])
        self.tm_cb.pack(fill="x")
        self.tm_cb.bind("<<ComboboxSelected>>", lambda e: self.tame_calc())
        # 食べ物データが無い恐竜のときだけ出す（キブルを使わない恐竜が多いので既定は隠す）
        self.tm_kibble = tk.BooleanVar(value=False)
        self.tm_kibble_chk = self._check(right, "キブルも候補に出す",
                                         self.tm_kibble, self.tame_select)

        r2 = tk.Frame(right, bg=th.CARD)
        r2.pack(fill="x", pady=(10, 0))
        tk.Label(r2, text="いまの食料値", bg=th.CARD, fg=th.INK, font=F["cute"],
                 width=12, anchor="w").pack(side="left")
        self.tm_curfood = tk.StringVar(value="0")
        th.soft_entry(r2, self.tm_curfood, width=8).pack(side="left", ipady=3)
        tk.Label(right, text="0 のままでOK。入れると、それを消費しきるまでの"
                            "待ち時間も足して計算します",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=330,
                 justify="left").pack(anchor="w", pady=(2, 8))

        self.tm_result = tk.Label(right, text="恐竜をえらんでね", bg=th.FIELD,
                                  fg=th.INK, font=F["ui"], justify="left",
                                  anchor="nw", padx=12, pady=10, width=40, height=11)
        self.tm_result.pack(fill="x")
        self.tm_note = tk.Label(right, text="", bg=th.CARD, fg=th.PINK_DK,
                                font=F["small"], anchor="w", justify="left",
                                wraplength=330)
        self.tm_note.pack(fill="x", pady=(4, 0))

        btm = tk.Frame(right, bg=th.CARD)
        btm.pack(side="bottom", fill="x", pady=(12, 0))
        th.RoundButton(btm, "⏰ タイマーにする", self.create_tame, kind="primary",
                       bg=th.CARD, font=F["cute_b"], padx=18).pack(side="right")
        th.RoundButton(btm, "やめる", self.destroy, kind="soft", bg=th.CARD,
                       font=F["cute"]).pack(side="right", padx=8)

        for v in (self.tm_level, self.tm_curfood):
            v.trace_add("write", lambda *a: self.tame_calc())

    def taming_mults(self):
        c = self.app.cfg
        return {"taming": c.get("taming_speed", 1.0),
                "food_drain": c.get("food_drain", 1.0),
                "wild_food_drain": c.get("wild_food_drain", 1.0),
                "torpor_drain": c.get("torpor_drain", 1.0)}

    def tame_refresh_list(self):
        q = (self.tm_q.get() or "").strip().lower()
        db = self.app.tdb
        # 恐竜データ側の日本語名を借りて、日本語でも探せるようにする。
        # 「Rex」で「Astral T-Rex」が先に出ないよう、前方一致を優先する。
        hits, subs = [], []
        for n in db.names():
            sp = self.app.db.by_name.get(n)
            jp = (sp or {}).get("jp", "")
            low = n.lower()
            if not q:
                subs.append((n, jp))
            elif low.startswith(q) or jp.startswith(q):
                hits.append((n, jp))
            elif q in low or q in jp:
                subs.append((n, jp))
        names = hits + subs
        self.tm_names = names
        self.tm_list.delete(0, "end")
        for n, jp in names[:400]:
            self.tm_list.insert("end", "  %s%s" % (n, ("   " + jp.split(" ")[0])
                                                   if jp else ""))
        if names:
            self.tm_list.selection_clear(0, "end")
            self.tm_list.selection_set(0)
            self.tame_select()
        else:
            # 見つからなかったときに前の恐竜が居座らないようにする
            self.tm_sp_name = None
            self.tm_foods = []
            self.tm_cb["values"] = []
            self.tm_result.config(text="その名前の恐竜は見つかりません")
            self.tm_note.config(text="")

    def tame_select(self):
        sel = self.tm_list.curselection()
        if not sel:
            return
        self.tm_sp_name = self.tm_names[sel[0]][0]
        sp = self.app.tdb.get(self.tm_sp_name)
        known = bool(sp.get("eats"))
        # 食べ物データが無いときだけ「キブルも出す」を見せる
        if known:
            self.tm_kibble_chk.pack_forget()
        else:
            self.tm_kibble_chk.pack(anchor="w", pady=(2, 0))
        foods = self.app.tdb.foods_for(sp, include_kibble=self.tm_kibble.get())
        self.tm_foods = foods
        self.tm_cb["values"] = [self.app.tdb.food_label(x) for x in foods]
        if foods:
            self.tm_cb.current(0)
        self.tame_calc()

    def _tame_result(self):
        name = getattr(self, "tm_sp_name", None)
        if not name or not getattr(self, "tm_foods", None):
            return None, None, "恐竜をえらんでね"
        sp = self.app.tdb.get(name)
        i = self.tm_cb.current()
        if not 0 <= i < len(self.tm_foods):
            return None, None, "食べ物をえらんでね"
        try:
            level = max(1, int(float(self.tm_level.get() or 1)))
        except ValueError:
            return None, None, "レベルは数字で"
        try:
            cur = max(0.0, float(self.tm_curfood.get() or 0))
        except ValueError:
            return None, None, "いまの食料値は数字で"
        r = taming.calc(self.app.tdb, sp, level, self.tm_foods[i],
                        self.taming_mults(), cur)
        if not r.get("ok"):
            return None, None, r.get("why") or "計算できません"
        return sp, r, None

    def tame_calc(self):
        if not hasattr(self, "tm_result"):
            return
        sp, r, err = self._tame_result()
        if err:
            self.tm_result.config(text=err)
            self.tm_note.config(text="")
            return
        lines = [
            "🍖 必要な数    %d 個" % r["pieces"],
            "⏰ かかる時間  %s" % fmt_dur(r["seconds"]),
        ]
        if r["wait_seconds"]:
            lines.append("   食べ始めまで %s（合計 %s）" % (
                fmt_dur(r["wait_seconds"]), fmt_dur(r["total_seconds"])))
        if r["te_known"]:
            lines.append("📈 テイム効率  %.1f%%  → +%dLv（Lv%d になる）" % (
                r["te"] * 100, r["bonus"], r["level_after"]))
        else:
            lines.append("📈 テイム効率  データ無し（この恐竜は出せません）")
        lines.append("")
        if r["torpor_per_sec"] > 0:
            lines.append("😵 気絶値      %s（%.1f/秒 で減る）" % (
                "{:,}".format(int(r["total_torpor"])), r["torpor_per_sec"]))
            lines.append("   起きるまで  %s" % fmt_dur(r["wake_seconds"]))
            if r["torpor_needed"] > 0:
                need = dict(r["narcotics"])
                lines.append("   麻酔薬 %d / バイオトキシン %d" % (
                    need.get("麻酔薬", 0), need.get("バイオトキシン", 0)))
            else:
                lines.append("   麻酔は要りません")
        else:
            lines.append("😵 気絶値      データ無し")
        self.tm_result.config(text="\n".join(lines))

        notes = []
        if r["food_from"]:
            notes.append("※ 変種なので %s の食べ物データを使っています" % r["food_from"])
        elif r["unconfirmed_food"]:
            notes.append("⚠ この恐竜の食べ物データが無いので、一般的な値で計算した"
                         "目安です")
            notes.append("　 テイム方法が特殊な恐竜（カルカロなど）はキブルを"
                         "使わないので、キブルは既定で出していません")
        if r["non_violent"]:
            notes.append("※ 気絶させずにテイムする恐竜です")
        self.tm_note.config(text="\n".join(notes))

    def create_tame(self):
        sp, r, err = self._tame_result()
        if err:
            self.tm_note.config(text="⚠ " + err)
            return
        label = "%s のテイム" % self.tm_sp_name
        t = BreedTimer("custom", label, r["total_seconds"], self.tm_sp_name)
        t.note = "%s × %d個 ／ %s" % (
            self.app.tdb.food_label(self.tm_foods[self.tm_cb.current()]),
            r["pieces"], ("TE %.1f%% → Lv%d" % (r["te"] * 100, r["level_after"]))
            if r["te_known"] else "TE不明")
        self.app.add_timer(t)
        self.destroy()

    def create_ark(self):
        self.ark_err.config(text="")
        if not self.sp:
            self._warn(self.ark_err, "恐竜をえらんでください")
            return
        kinds = tuple(k for k, v in self.kv.items() if v.get())
        if not kinds:
            self._warn(self.ark_err, "つくるタイマーを1つ以上えらんでください")
            return
        label = self.var_label.get().strip() or self.sp["name"]
        offset = 0.0
        offset_kinds = None
        mode = self.var_start.get()
        if mode == "left":
            left = parse_duration(self.var_left.get())
            if left is None:
                self._warn(self.ark_err, "残り時間の書き方がわかりません（例 1:23:45）")
                return
            base = {"hatch": self.calc["hatch"], "gestation": self.calc["gestation"],
                    "mature": self.calc["mature"],
                    "imprint": self.calc["imprint_interval"],
                    "matingcd": self.calc["cd_lo"]}.get(kinds[0], left)
            offset = max(0.0, base - left)
        elif mode == "mature":
            p = self._pct()
            if p is None:
                self._warn(self.ark_err, "成熟度は 0〜100 の数字で入れてください")
                return
            offset = self.calc["mature"] * p
            # 成熟度が進んでいる = もう生まれているので、孵化・妊娠は作らない
            if p > 0:
                kinds = tuple(k for k in kinds if k not in ("hatch", "gestation"))
                if not kinds:
                    self._warn(self.ark_err,
                               "成熟度から作るときは、成長・刷り込み・再交配CD から"
                               "選んでください")
                    return
            # 再交配CDは成熟度とは関係ないので、ずらすのは成長と刷り込みだけ
            offset_kinds = {"mature", "imprint"}
        made = self.app.make_timers(self.sp, label, self.calc, kinds, offset=offset,
                                    offset_kinds=offset_kinds)
        if not made:
            self._warn(self.ark_err, "この恐竜にはそのタイマーがありません")
            return
        for t in made:
            self.app.timers.append(t)
        self.app.rebuild_list()
        self.app.save_timers()
        self.destroy()


# ---------------------------------------------------------------- 更新
class UpdateDialog(tk.Toplevel):
    """GitHub を見て、新しい版があれば内容を見せてから入れ替える。"""

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.F = app.F
        self.info = None
        self.asset = None
        self.busy = False
        self.title("更新のかくにん")
        self.configure(bg=th.BG)
        # 中身（見出し＋更新内容13行＋ボタン）にぴったり合う大きさ。
        # 大きすぎるとカードの下に余白が出るし、小さいとボタンが隠れる。
        self.geometry("560x430")
        self.minsize(520, 430)
        self.transient(app)
        self.attributes("-topmost", bool(app.cfg["always_on_top"]))

        card = th.Card(self, bg=th.BG)
        card.pack(fill="both", expand=True, padx=10, pady=10)
        b = card.body

        self.lbl_head = tk.Label(b, text="いま v%s です" % APP_VERSION, bg=th.CARD,
                                 fg=th.INK, font=self.F["cute_b"], anchor="w")
        self.lbl_head.pack(fill="x")
        self.lbl_state = tk.Label(b, text="たしかめています…", bg=th.CARD,
                                  fg=th.INK_SUB, font=self.F["small"], anchor="w",
                                  justify="left", wraplength=490)
        self.lbl_state.pack(fill="x", pady=(2, 8))

        # ボタンを先に下へ確保する。あとから置くと、更新内容の欄が場所を
        # 全部取ってボタンが窓の外へ押し出されてしまう。
        btm = tk.Frame(b, bg=th.CARD)
        btm.pack(side="bottom", fill="x", pady=(10, 0))
        self.btn_go = th.RoundButton(btm, "いますぐ更新", self.do_update,
                                     kind="primary", bg=th.CARD,
                                     font=self.F["cute_b"], padx=22)
        th.RoundButton(btm, "キャンセル", self.destroy, kind="soft", bg=th.CARD,
                       font=self.F["cute"]).pack(side="right", padx=8)
        th.RoundButton(btm, "ページを開く", self.open_page, kind="ghost", bg=th.CARD,
                       font=self.F["small"]).pack(side="left")
        self.bar = th.RoundProgress(b, bg=th.CARD, color=th.LAV, height=6)

        box = tk.Frame(b, bg=th.FIELD)
        box.pack(fill="both", expand=True)
        # Text の既定は 80x24 で、そのままだと窓より大きい高さを要求してしまう。
        # 明示的に小さくして、あふれた分はスクロールで見せる。
        self.txt = tk.Text(box, bg=th.FIELD, fg=th.INK, font=self.F["ui"],
                           relief="flat", bd=0, wrap="word", padx=12, pady=10,
                           highlightthickness=0, width=1, height=13)
        vs = ttk.Scrollbar(box, orient="vertical", command=self.txt.yview,
                           style="Cute.Vertical.TScrollbar")
        self.txt.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt.configure(state="disabled")

        # 別スレッドの結果は箱に置くだけにして、本体側が見に行く。
        # Tk のウィジェットをワーカースレッドから触るのは安全ではないため。
        self._got_info = None
        self._prog = None
        self._done = None
        threading.Thread(target=self._check, daemon=True).start()
        self.after(120, self._poll)

    def _check(self):
        self._got_info = updater.check()

    def _poll(self):
        if not self.winfo_exists():
            return
        if self._got_info is not None:
            info, self._got_info = self._got_info, None
            self._show(info)
        if self._prog is not None:
            got, total = self._prog
            self._prog = None
            if total:
                self.bar.set(got / total)
        if self._done is not None:
            ok, why = self._done
            self._done = None
            if ok:
                self.app.on_close()   # バッチがこのプロセスの終了を待っている
                return
            self._failed(why)
        self.after(120, self._poll)

    def _set_text(self, s):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", s)
        self.txt.configure(state="disabled")

    def _show(self, info):
        if not self.winfo_exists():
            return
        if not info.get("ok"):
            self.lbl_state.config(text="⚠ " + info.get("why", "失敗しました"),
                                  fg=th.PINK_DK)
            self._set_text("インターネットにつながっているか確かめてください。\n"
                           "「ページを開く」から手で取りにいくこともできます。")
            return
        self.info = info
        tag = info["tag"]
        body = (info.get("body") or "").lstrip("﻿").strip()
        self._set_text(body or "（更新内容が書かれていません）")
        if not updater.is_newer(tag, APP_VERSION):
            self.lbl_state.config(text="いちばん新しい版です（最新 %s）" % tag,
                                  fg=th.MINT)
            return

        kind = updater.install_kind()
        self.asset = updater.pick_asset(info, kind)
        self.lbl_head.config(text="v%s  →  %s があります" % (APP_VERSION, tag))
        if kind == "source":
            self.lbl_state.config(
                text="ソースから動いているので、ここからは更新できません。"
                     "git pull してください", fg=th.PINK_DK)
            return
        if not self.asset:
            self.lbl_state.config(text="⚠ 入れ替えられるファイルが見つかりません",
                                  fg=th.PINK_DK)
            return
        how = {"installer": "インストーラで入れ替えます",
               "onedir": "フォルダを入れ替えます",
               "onefile": "exe を入れ替えます"}.get(kind, "入れ替えます")
        self.lbl_state.config(
            text="%s（%.1f MB）で%s。設定とタイマーはそのまま残ります"
                 % (self.asset["name"], self.asset["size"] / 1024 / 1024, how),
            fg=th.INK_SUB)
        self.btn_go.pack(side="right")

    # ---- 更新 ----
    def open_page(self):
        import webbrowser
        webbrowser.open((self.info or {}).get("url") or updater.RELEASES_PAGE)

    def do_update(self):
        if self.busy or not self.asset:
            return
        self.busy = True
        self.btn_go.set_text("更新中…")
        self.bar.pack(side="bottom", fill="x", pady=(8, 0))
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            path = updater.download(
                self.asset, lambda got, total: setattr(self, "_prog", (got, total)))
            ok, why = updater.apply(path)
        except Exception as e:
            ok, why = False, "%s: %s" % (e.__class__.__name__, e)
        self._done = (ok, why)

    def _failed(self, why):
        self.busy = False
        self.btn_go.set_text("いますぐ更新")
        self.bar.pack_forget()
        self.lbl_state.config(text="⚠ 更新できませんでした: %s" % why, fg=th.PINK_DK)


# ---------------------------------------------------------------- 設定
class SettingsDialog(tk.Toplevel):
    MULTS = [
        ("egg_hatch_speed", "EggHatchSpeedMultiplier（孵化・妊娠）"),
        ("baby_mature_speed", "BabyMatureSpeedMultiplier（成長）"),
        ("cuddle_interval_mult", "BabyCuddleIntervalMultiplier（刷り込み間隔）"),
        ("mating_interval_mult", "MatingIntervalMultiplier（再交配CD）"),
        ("imprint_amount_mult", "BabyImprintAmountMultiplier（刷り込み量）"),
    ]
    TAME_MULTS = [
        ("taming_speed", "TamingSpeedMultiplier（テイム速度）"),
        ("food_drain", "DinoCharacterFoodDrainMultiplier（食料の減り）"),
        ("wild_food_drain", "WildDinoCharacterFoodDrainMultiplier（野生の食料）"),
        ("torpor_drain", "WildDinoTorporDrainMultiplier（気絶値の減り）"),
    ]

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.F = app.F
        self.title("設定")
        self.configure(bg=th.BG)
        self.geometry("620x730")
        self.transient(app)
        self.attributes("-topmost", bool(app.cfg["always_on_top"]))

        sw = FlowFrame(self, bg=th.BG, gap_x=8, gap_y=6)
        sw.pack(fill="x", padx=18, pady=(16, 8))
        # 保存ボタンとエラー欄を先に下へ確保してから、中身を入れる。
        # 逆にすると、中身が長いタブでボタンが窓の外へ出てしまう。
        self.err = tk.Label(self, text="", bg=th.BG, fg=th.PINK_DK,
                            font=self.F["small"], anchor="w", justify="left",
                            wraplength=540)
        btm = tk.Frame(self, bg=th.BG)
        btm.pack(side="bottom", fill="x", padx=18, pady=(0, 14))
        self.err.pack(side="bottom", fill="x", padx=18)
        self.holder = tk.Frame(self, bg=th.BG)
        self.holder.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.btns, self.pages = {}, {}
        for key, label in (("snd", "🔔 音と通知"), ("timer", "⏰ タイマー"),
                           ("ark", "🦖 ARK倍率")):
            self.btns[key] = sw.add(th.RoundButton(
                sw, label, lambda k=key: self.switch(k), kind="soft", bg=th.BG,
                font=self.F["cute"]))
            self.pages[key] = th.Card(self.holder, bg=th.BG)
        self._build_sound(self.pages["snd"].body)
        self._build_timer(self.pages["timer"].body)
        self._build_ark(self.pages["ark"].body)

        th.RoundButton(btm, "保存する", self.save, kind="primary", bg=th.BG,
                       font=self.F["cute_b"], padx=28).pack(side="right")
        th.RoundButton(btm, "やめる", self.destroy, kind="soft", bg=th.BG,
                       font=self.F["cute"]).pack(side="right", padx=8)
        tk.Label(btm, text="v%s ・恐竜データ %d種" % (APP_VERSION,
                                                    len(app.db.species)),
                 bg=th.BG, fg=th.INK_SUB, font=self.F["small"]).pack(side="left")
        self.switch("snd")

    def switch(self, which):
        for card in self.pages.values():
            card.pack_forget()
        self.pages[which].pack(fill="both", expand=True)
        for key, b in self.btns.items():
            on = key == which
            b.fill = th.PINK if on else th.BG_SOFT
            b.itemconfigure(b.shape, fill=b.fill)
            b.itemconfigure(b.label, fill="#FFFFFF" if on else th.INK)

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

        tk.Label(f, text="\nポップアップが自分で消えるまで（秒／0でずっと出しっぱなし）",
                 bg=th.CARD, fg=th.INK, font=F["cute"]).pack(anchor="w")
        row3 = tk.Frame(f, bg=th.CARD)
        row3.pack(anchor="w", pady=(4, 0))
        self.v_pc_pre = tk.StringVar(value=str(int(cfg.get("popup_close_prewarn") or 0)))
        self.v_pc_done = tk.StringVar(value=str(int(cfg.get("popup_close_done") or 0)))
        for text, var in (("予告", self.v_pc_pre), ("鳴ったとき", self.v_pc_done)):
            tk.Label(row3, text=text, bg=th.CARD, fg=th.INK_SUB,
                     font=F["small"]).pack(side="left", padx=(0, 4))
            th.soft_entry(row3, var, width=5).pack(side="left", padx=(0, 14), ipady=3)

    def _vol_changed(self, v):
        self.vol = v
        self.lbl_vol.config(text="%d%%" % round(v * 100))
        self.app.cfg["volume"] = v  # 試聴にすぐ反映させる

    def _preview_vol(self):
        snd.play_async(self.pick_done.get() or snd.DEFAULT_DONE,
                       self.vol, SOUND_CACHE)

    # ------------------------------------------------ タイマーの設定
    def _build_timer(self, f):
        F = self.F
        tk.Label(f, text="さくっとボタン", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        tk.Label(f, text="ワンクリックでタイマーを作るボタンです。"
                         "名前と長さを自由に変えられます",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w",
                                                                  pady=(0, 6))
        hdr = tk.Frame(f, bg=th.CARD)
        hdr.pack(fill="x")
        tk.Label(hdr, text="なまえ", bg=th.CARD, fg=th.INK_SUB, font=F["small"],
                 width=12, anchor="w").pack(side="left")
        tk.Label(hdr, text="長さ", bg=th.CARD, fg=th.INK_SUB, font=F["small"],
                 anchor="w").pack(side="left")

        self.quick_rows_box = tk.Frame(f, bg=th.CARD)
        self.quick_rows_box.pack(fill="x", pady=(2, 6))
        self.quick_rows = []
        for it in self.app.quick_specs():
            self._add_quick_row(it["label"], it["sec"])

        bar = tk.Frame(f, bg=th.CARD)
        bar.pack(fill="x", pady=(0, 14))
        th.RoundButton(bar, "＋ 追加", lambda: self._add_quick_row("", 300),
                       kind="soft", bg=th.CARD, font=F["small"],
                       padx=12, pady=5).pack(side="left")
        th.RoundButton(bar, "はじめの並びに戻す", self._reset_quick, kind="ghost",
                       bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left", padx=6)
        tk.Label(bar, text="長さは 5:00 / 25m / 90（=90分）", bg=th.CARD,
                 fg=th.INK_SUB, font=F["small"]).pack(side="left", padx=6)

        tk.Label(f, text="終わったタイマーの片づけかた", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        self.v_autoclear = tk.BooleanVar(
            value=bool(self.app.cfg.get("auto_clear_done", True)))
        arow = tk.Frame(f, bg=th.CARD)
        arow.pack(anchor="w", pady=(2, 0))
        tk.Radiobutton(arow, text="終わってから", variable=self.v_autoclear,
                       value=True, bg=th.CARD, fg=th.INK, activebackground=th.CARD,
                       activeforeground=th.INK, selectcolor=th.FIELD,
                       font=F["cute"], bd=0, highlightthickness=0).pack(side="left")
        self.v_clear_min = tk.StringVar(
            value="%g" % (int(self.app.cfg.get("auto_clear_sec", 600) or 600) / 60.0))
        th.soft_entry(arow, self.v_clear_min, width=5).pack(side="left", padx=6,
                                                            ipady=3)
        tk.Label(arow, text="分たったら自動で消す", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        tk.Radiobutton(f, text="「✔ できた」を押したときだけ消す（自動では消さない）",
                       variable=self.v_autoclear, value=False, bg=th.CARD,
                       fg=th.INK, activebackground=th.CARD, activeforeground=th.INK,
                       selectcolor=th.FIELD, font=F["cute"], bd=0,
                       highlightthickness=0, anchor="w").pack(anchor="w")
        tk.Label(f, text="どちらでも、終わったタイマーには「✔ できた」ボタンが出ます。"
                         "刷り込みの「✔ できた」待ち・くり返し中・一時停止中は自動では"
                         "消えません。起動前に終わっていた分は、起動してからこの時間だけ"
                         "残ります（最短10秒）",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"],
                 wraplength=520, justify="left").pack(anchor="w", pady=(2, 12))

        tk.Label(f, text="消すとき", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        self.v_confirm = tk.BooleanVar(
            value=bool(self.app.cfg.get("confirm_delete", True)))
        self._check(f, "✕ を押したとき「消しますか？」と確認する",
                    self.v_confirm).pack(anchor="w")
        tk.Label(f, text="オフにすると、押した瞬間に消えます（元に戻せません）",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w")

    def _add_quick_row(self, label, sec):
        if len(self.quick_rows) >= 8:
            return
        F = self.F
        row = tk.Frame(self.quick_rows_box, bg=th.CARD)
        row.pack(fill="x", pady=1)
        v_label = tk.StringVar(value=label)
        v_time = tk.StringVar(value=fmt_dur(sec))
        th.soft_entry(row, v_label, width=12).pack(side="left", ipady=2)
        th.soft_entry(row, v_time, width=9).pack(side="left", padx=6, ipady=2)
        rec = {"row": row, "label": v_label, "time": v_time}
        th.RoundButton(row, "✕", lambda r=rec: self._del_quick_row(r),
                       kind="danger", bg=th.CARD, font=F["small"], padx=9,
                       pady=4).pack(side="left")
        self.quick_rows.append(rec)

    def _del_quick_row(self, rec):
        rec["row"].destroy()
        if rec in self.quick_rows:
            self.quick_rows.remove(rec)

    def _reset_quick(self):
        for rec in list(self.quick_rows):
            self._del_quick_row(rec)
        for it in DEFAULT_CONFIG["quick_buttons"]:
            self._add_quick_row(it["label"], it["sec"])

    def _read_quick(self):
        """(一覧, エラー文)。名前が空なら長さから作る。"""
        out = []
        for rec in self.quick_rows:
            text = rec["time"].get().strip()
            if not text:
                continue
            sec = parse_duration(text)
            if sec is None or sec <= 0:
                return None, "「%s」は長さとして読めません（例 5:00）" % text
            out.append({"label": rec["label"].get().strip() or fmt_dur(sec),
                        "sec": sec})
        if not out:
            return None, "さくっとボタンを1つ以上のこしてください"
        return out, None

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

        tk.Label(f, text="\nテイムの倍率", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        for key, text in self.TAME_MULTS:
            row = tk.Frame(f, bg=th.CARD)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=text, bg=th.CARD, fg=th.INK, font=F["ui"],
                     anchor="w", width=40).pack(side="left")
            v = tk.StringVar(value=str(self.app.cfg.get(key, 1.0)))
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
        self.err.config(text="")
        try:
            for key, _ in self.MULTS + self.TAME_MULTS:
                val = float(self.vars[key].get())
                if val <= 0:
                    raise ValueError(key)
                self.app.cfg[key] = val
            self.app.cfg["prewarn_sec"] = max(0, int(float(self.v_pre.get())))
            self.app.cfg["popup_close_prewarn"] = max(0, int(float(self.v_pc_pre.get())))
            self.app.cfg["popup_close_done"] = max(0, int(float(self.v_pc_done.get())))
            self.app.cfg["auto_clear_sec"] = max(
                10, int(float(self.v_clear_min.get()) * 60))
        except ValueError:
            self.switch("ark")
            self.err.config(text="⚠ 倍率は0より大きい数字で入れてください")
            return
        quick, qerr = self._read_quick()
        if qerr:
            self.switch("timer")
            self.err.config(text="⚠ " + qerr)
            return
        c = self.app.cfg
        c["quick_buttons"] = quick
        c["confirm_delete"] = bool(self.v_confirm.get())
        c["auto_clear_done"] = bool(self.v_autoclear.get())
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
        self.app.refresh_quick()
        self.destroy()


def main():
    if not os.path.exists(os.path.join(DATA_DIR, "species.json")):
        print("data/species.json がありません。tools/build_species_db.py を実行してください。")
    App().mainloop()


if __name__ == "__main__":
    main()
