# -*- coding: utf-8 -*-
"""🧮 パーセントの平均を出すだけの小さな電卓。

3つ入れて、足して3で割る。それだけ。空けた欄は数に入れないので、
2つだけ入れれば2つの平均になる。

「50」でも「50%」でも「0.5」でもいいように、ゆるく読む。
"""
from __future__ import annotations

import tkinter as tk

import theme as th

SLOTS = 3


def parse_percent(text):
    """「50」「50%」「５０％」などを 50.0 にする。読めなければ None。"""
    t = (text or "").strip()
    if not t:
        return None
    # 全角を半角に寄せてから、数字に関係ない字を落とす
    t = t.translate(str.maketrans("０１２３４５６７８９．％－",
                                  "0123456789.%-"))
    t = t.replace("%", "").replace(",", "").replace(" ", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def average(values):
    """空でないものだけで平均する。ひとつも無ければ None。"""
    got = [v for v in values if v is not None]
    if not got:
        return None
    return sum(got) / len(got)


class CalcPage(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=th.BG)
        self.app = app
        F = app.F

        card = th.Card(self, bg=th.BG)
        card.pack(fill="x")
        c = card.body
        tk.Label(c, text="🧮 パーセントの平均", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        tk.Label(c, text="3つ入れると平均を出します。"
                         "空けた欄は数に入れないので、2つだけでも大丈夫です",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"],
                 wraplength=760, justify="left").pack(anchor="w", pady=(0, 8))

        row = tk.Frame(c, bg=th.CARD)
        row.pack(fill="x")
        self.vars = []
        for i in range(SLOTS):
            if i:
                tk.Label(row, text="＋", bg=th.CARD, fg=th.INK_SUB,
                         font=F["cute"]).pack(side="left", padx=4)
            v = tk.StringVar()
            v.trace_add("write", lambda *a: self.recalc())
            ent = th.soft_entry(row, v, width=8,
                                font=("Segoe UI Semibold", 16))
            ent.pack(side="left", ipady=4)
            tk.Label(row, text="%", bg=th.CARD, fg=th.INK,
                     font=F["cute"]).pack(side="left", padx=(2, 0))
            self.vars.append(v)
        th.RoundButton(row, "けす", self.clear, kind="ghost", bg=th.CARD,
                       font=F["small"], padx=12, pady=6).pack(side="left",
                                                              padx=12)

        self.lbl_out = tk.Label(c, text="", bg=th.CARD, fg=th.PINK_DK,
                                font=F["num"], anchor="w")
        self.lbl_out.pack(fill="x", pady=(10, 0))
        self.lbl_sub = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="w")
        self.lbl_sub.pack(fill="x")
        self.recalc()

    def values(self):
        return [parse_percent(v.get()) for v in self.vars]

    def clear(self):
        for v in self.vars:
            v.set("")

    def recalc(self):
        got = self.values()
        avg = average(got)
        if avg is None:
            self.lbl_out.config(text="—")
            self.lbl_sub.config(text="数字を入れてください")
            return
        used = [v for v in got if v is not None]
        # 割り切れるときは小数を出さない（33.33% と 40% を並べたい）
        txt = ("%g" % round(avg, 4)) if abs(avg - round(avg)) > 1e-9 \
            else ("%d" % round(avg))
        self.lbl_out.config(text="%s %%" % txt)
        self.lbl_sub.config(
            text="（%s）÷ %d ＝ %s%%　／　合計 %g%%"
                 % (" ＋ ".join("%g" % v for v in used), len(used),
                    ("%.4f" % avg).rstrip("0").rstrip("."), sum(used)))
