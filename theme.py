# -*- coding: utf-8 -*-
"""かわいい系パステルUIキット（tkinter標準のみ）。

tkinter/ttk は角丸を持たないので、カード・ボタン・バッジ・進捗バーは
Canvas に自前で描いている。
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

# ---------------------------------------------------------------- パレット
BG = "#FBF7FA"        # ほんのり桜色の生成り
BG_SOFT = "#F4ECF4"
CARD = "#FFFFFF"
SHADOW = "#F1E5EF"
LINE = "#EFE6EF"
FIELD = "#F8F3F8"

INK = "#4C4457"       # 文字
INK_SUB = "#A99CB4"   # 補助文字

PINK = "#FF9BBB"
PINK_DK = "#F4749E"
LAV = "#B79CF0"
MINT = "#68D2B0"
SKY = "#88C6F7"
LEMON = "#FFD275"
PEACH = "#FFAD8E"
RED = "#FF7B7B"

# 種類ごとの見た目 (絵文字, 色, 表示名)
KIND_STYLE = {
    "custom": ("⏰", PEACH, "タイマー"),
    "hatch": ("🥚", LEMON, "孵化"),
    "gestation": ("🌸", PINK, "妊娠"),
    "mature": ("🌱", MINT, "成長"),
    "imprint": ("💗", SKY, "刷り込み"),
    "matingcd": ("💞", LAV, "再交配"),
}

JP = "Yu Gothic UI"
CUTE = "UD デジタル 教科書体 NP"


def fonts():
    """使えるフォントを見て決める（無ければ Yu Gothic UI に落とす）。"""
    fams = set(tkfont.families())
    cute = CUTE if CUTE in fams else JP
    return {
        "ui": (JP, 10),
        "ui_b": (JP, 10, "bold"),
        "small": (JP, 9),
        "cute": (cute, 11),
        "cute_b": (cute, 12, "bold"),
        "head": (cute, 15, "bold"),
        "num": ("Segoe UI Semibold", 26),
        "num_s": ("Segoe UI Semibold", 15),
    }


def make_icon(size=64):
    """ピンクの時計アイコンを生成（外部ファイル不要）"""
    img = tk.PhotoImage(width=size, height=size)
    c = (size - 1) / 2.0
    r = c - 1
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            dx, dy = x - c, y - c
            d = (dx * dx + dy * dy) ** 0.5
            if d > r:
                row.append(BG)
            elif d > r - max(1, size // 16):
                row.append(PINK_DK)
            else:
                row.append(PINK)
            # 針（12時方向と3時方向）
            if abs(dx) <= size / 32 and -r * 0.62 <= dy <= 0:
                row[-1] = "#FFFFFF"
            if abs(dy) <= size / 32 and 0 <= dx <= r * 0.45:
                row[-1] = "#FFFFFF"
        rows.append("{" + " ".join(row) + "}")
    img.put(" ".join(rows))
    for y in range(size):
        for x in range(size):
            dx, dy = x - c, y - c
            if (dx * dx + dy * dy) ** 0.5 > r:
                img.transparency_set(x, y, True)
    return img


F = {}


def init(root):
    """フォント辞書を用意し、ttk（スクロールバー等）にも色を入れる。"""
    global F
    F = fonts()
    from tkinter import ttk

    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure("Cute.Vertical.TScrollbar", background=BG_SOFT, troughcolor=BG,
                 bordercolor=BG, arrowcolor=INK_SUB, borderwidth=0, relief="flat",
                 gripcount=0, arrowsize=12)
    st.map("Cute.Vertical.TScrollbar", background=[("active", PINK)])
    st.configure("Cute.Horizontal.TScale", background=CARD, troughcolor=BG_SOFT,
                 bordercolor=CARD, darkcolor=PINK, lightcolor=PINK, borderwidth=0)
    st.configure("Cute.TCombobox", fieldbackground=FIELD, background=FIELD,
                 foreground=INK, arrowcolor=INK_SUB, borderwidth=0, padding=6)
    st.map("Cute.TCombobox", fieldbackground=[("readonly", FIELD)],
           selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", INK)])
    return F


# ---------------------------------------------------------------- 描画部品
def round_rect(cv, x1, y1, x2, y2, r, **kw):
    """Canvas に角丸長方形を描く（smooth ポリゴン）。"""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return cv.create_polygon(pts, smooth=True, splinesteps=24, **kw)


class RoundButton(tk.Canvas):
    """角丸ボタン。kind: primary / soft / ghost / danger"""

    SCHEME = {
        "primary": (PINK, PINK_DK, "#FFFFFF"),
        "accent": (LAV, "#9F7DE8", "#FFFFFF"),
        "mint": (MINT, "#4FC3A0", "#FFFFFF"),
        "soft": (BG_SOFT, "#E8DCEA", INK),
        "ghost": (CARD, BG_SOFT, INK_SUB),
        "danger": ("#FFEDED", "#FFD9D9", RED),
    }

    def __init__(self, master, text, command=None, kind="soft", bg=BG,
                 font=None, padx=16, pady=8, radius=None, width=None):
        self.font = font or F.get("cute", (JP, 11))
        fo = tkfont.Font(font=self.font)
        w = width or (fo.measure(text) + padx * 2)
        h = fo.metrics("linespace") + pady * 2
        super().__init__(master, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
        self.command = command
        self.fill, self.hover, self.fg = self.SCHEME.get(kind, self.SCHEME["soft"])
        r = radius if radius is not None else h / 2
        self.shape = round_rect(self, 1, 1, w - 1, h - 1, r, fill=self.fill, outline="")
        self.label = self.create_text(w / 2, h / 2 + 1, text=text, fill=self.fg,
                                      font=self.font)
        self.bind("<Enter>", lambda e: self.itemconfigure(self.shape, fill=self.hover))
        self.bind("<Leave>", lambda e: self.itemconfigure(self.shape, fill=self.fill))
        self.bind("<Button-1>", lambda e: self.itemconfigure(self.shape, fill=self.hover))
        self.bind("<ButtonRelease-1>", self._click)
        self.configure(cursor="hand2")

    def _click(self, _e=None):
        self.itemconfigure(self.shape, fill=self.fill)
        if self.command:
            self.command()

    def set_text(self, text):
        self.itemconfigure(self.label, text=text)


class PillBadge(tk.Canvas):
    """種類バッジ（絵文字＋名前の角丸ピル）"""

    def __init__(self, master, text, color, bg=CARD, font=None, padx=12, pady=4):
        self.font = font or F.get("small", (JP, 9))
        fo = tkfont.Font(font=self.font)
        w = fo.measure(text) + padx * 2
        h = fo.metrics("linespace") + pady * 2
        super().__init__(master, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
        round_rect(self, 0, 0, w, h, h / 2, fill=color, outline="")
        self.create_text(w / 2, h / 2 + 1, text=text, fill="#FFFFFF", font=self.font)


class RoundProgress(tk.Canvas):
    """角丸の進捗バー"""

    def __init__(self, master, bg=CARD, color=PINK, height=10, track=BG_SOFT):
        super().__init__(master, height=height, bg=bg, highlightthickness=0, bd=0)
        self.color = color
        self.track = track
        self.h = height
        self.value = 0.0
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, value, color=None):
        self.value = max(0.0, min(1.0, value))
        if color and color != self.color:
            self.color = color
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.h
        if w < 4:
            return
        round_rect(self, 0, 0, w, h, h / 2, fill=self.track, outline="")
        fw = self.value * w
        if fw > 1:
            round_rect(self, 0, 0, max(fw, h), h, h / 2, fill=self.color, outline="")


class RoundSlider(tk.Canvas):
    """まるいつまみのスライダー（0.0〜1.0）"""

    def __init__(self, master, value=0.7, command=None, bg=CARD, color=PINK,
                 height=26, track_h=8, knob_r=9):
        super().__init__(master, height=height, bg=bg, highlightthickness=0, bd=0)
        self.value = max(0.0, min(1.0, value))
        self.command = command
        self.color = color
        self.track_h = track_h
        self.knob_r = knob_r
        self.h = height
        self.bind("<Configure>", lambda e: self._draw())
        for seq in ("<Button-1>", "<B1-Motion>"):
            self.bind(seq, self._from_event)
        self.configure(cursor="hand2")

    def _from_event(self, e):
        w = self.winfo_width()
        span = max(1, w - self.knob_r * 2)
        self.set((e.x - self.knob_r) / span)
        if self.command:
            self.command(self.value)

    def set(self, v):
        self.value = max(0.0, min(1.0, v))
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 8:
            return
        cy = self.h / 2
        r = self.knob_r
        th_ = self.track_h
        round_rect(self, r, cy - th_ / 2, w - r, cy + th_ / 2, th_ / 2,
                   fill=BG_SOFT, outline="")
        x = r + (w - r * 2) * self.value
        if x > r + 1:
            round_rect(self, r, cy - th_ / 2, x, cy + th_ / 2, th_ / 2,
                       fill=self.color, outline="")
        self.create_oval(x - r, cy - r, x + r, cy + r, fill="#FFFFFF",
                         outline=self.color, width=3)


class Card(tk.Canvas):
    """白い角丸カード。中身は self.body（普通のFrame）に入れる。"""

    PAD = 14

    def __init__(self, master, bg=BG, card=CARD, radius=20, pad=None):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, height=60)
        self.card_color = card
        self.radius = radius
        self.pad = self.PAD if pad is None else pad
        self.body = tk.Frame(self, bg=card)
        self._item = self.create_window(self.pad, self.pad, window=self.body, anchor="nw")
        self.bind("<Configure>", self._on_conf)
        self.body.bind("<Configure>", self._on_body)

    def _on_body(self, e):
        want = e.height + self.pad * 2
        if abs(int(self["height"]) - want) > 1:
            self.configure(height=want)

    def _on_conf(self, e):
        w, h = e.width, e.height
        self.delete("bgshape")
        round_rect(self, 4, 6, w - 4, h - 1, self.radius, fill=SHADOW,
                   outline="", tags="bgshape")
        round_rect(self, 4, 2, w - 4, h - 5, self.radius, fill=self.card_color,
                   outline="", tags="bgshape")
        self.tag_lower("bgshape")
        self.itemconfigure(self._item, width=max(1, w - self.pad * 2))


def soft_entry(master, textvariable=None, width=None, font=None, bg=CARD, **kw):
    """やわらかい見た目の入力欄"""
    e = tk.Entry(master, textvariable=textvariable, relief="flat", bd=0,
                 bg=FIELD, fg=INK, insertbackground=PINK_DK,
                 font=font or F.get("ui", (JP, 10)),
                 highlightthickness=2, highlightbackground=LINE, highlightcolor=PINK,
                 **({"width": width} if width else {}), **kw)
    return e


def label(master, text, bg=CARD, fg=None, font=None, **kw):
    return tk.Label(master, text=text, bg=bg, fg=fg or INK,
                    font=font or F.get("ui", (JP, 10)), **kw)


class Chip(tk.Canvas):
    """小さな丸いショートカット（5分 / 10分 …）"""

    def __init__(self, master, text, command, bg=BG, fill=CARD, fg=INK, font=None,
                 padx=13, pady=6):
        self.font = font or F.get("small", (JP, 9))
        fo = tkfont.Font(font=self.font)
        w = fo.measure(text) + padx * 2
        h = fo.metrics("linespace") + pady * 2
        super().__init__(master, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
        self.command = command
        self.fill = fill
        self.shape = round_rect(self, 1, 1, w - 1, h - 1, h / 2, fill=fill,
                                outline=LINE, width=1)
        self.create_text(w / 2, h / 2 + 1, text=text, fill=fg, font=self.font)
        self.bind("<Enter>", lambda e: self.itemconfigure(self.shape, fill="#FFF0F6"))
        self.bind("<Leave>", lambda e: self.itemconfigure(self.shape, fill=self.fill))
        self.bind("<ButtonRelease-1>", lambda e: command())
        self.configure(cursor="hand2")
