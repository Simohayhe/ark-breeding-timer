# -*- coding: utf-8 -*-
"""🏺 貢物とアーティファクトのページ。

マップを選んで、持っている数といる数を並べるだけ。数は ＋/－ で動かす。
スクショからの取り込みは、読めることを確かめてから足す（いまは手入力）。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import theme as th
import tribute as tb


class TributePage(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=th.BG)
        self.app = app
        self.F = app.F
        F = self.F
        self.map_name = ""
        self.rows = []

        # ---- 上: マップを選ぶ ----
        top = th.Card(self, bg=th.BG)
        top.pack(fill="x")
        c = top.body
        tk.Label(c, text="🏺 貢物とアーティファクト", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        tk.Label(c, text="マップごとに、持っている数といる数を控えておけます。"
                         "品目の名前はゲームの表記のままで大丈夫です",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=760,
                 justify="left").pack(anchor="w", pady=(0, 8))

        row = tk.Frame(c, bg=th.CARD)
        row.pack(fill="x")
        tk.Label(row, text="マップ", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left", padx=(0, 6))
        self.v_map = tk.StringVar()
        self.cb_map = ttk.Combobox(row, textvariable=self.v_map,
                                   state="readonly", width=24,
                                   style="Cute.TCombobox", font=F["ui"])
        self.cb_map.pack(side="left")
        self.cb_map.bind("<<ComboboxSelected>>", lambda e: self.pick_map())
        th.RoundButton(row, "＋ マップを足す", self.add_map, kind="soft",
                       bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left", padx=6)
        # 消すボタンは、マップがあるときだけ出す（無い時に押させない）
        self.drop_holder = tk.Frame(row, bg=th.CARD)
        self.drop_holder.pack(side="left")
        self.btn_drop_map = th.RoundButton(self.drop_holder, "このマップを消す",
                                           self.drop_map, kind="ghost",
                                           bg=th.CARD, font=F["small"],
                                           padx=12, pady=5)
        self.lbl_sum = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="w")
        self.lbl_sum.pack(fill="x", pady=(6, 0))

        # ---- 足す ----
        add = th.Card(self, bg=th.BG)
        add.pack(fill="x", pady=(8, 0))
        a = add.body
        tk.Label(a, text="品目を足す", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        r1 = tk.Frame(a, bg=th.CARD)
        r1.pack(fill="x", pady=(4, 2))
        self.v_new = tk.StringVar()
        th.soft_entry(r1, self.v_new, width=30).pack(side="left", ipady=3)
        tk.Label(r1, text=" いる数", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")
        self.v_need = tk.StringVar(value="0")
        th.soft_entry(r1, self.v_need, width=5).pack(side="left", padx=4,
                                                     ipady=3)
        th.RoundButton(r1, "＋ 足す", self.add_item, kind="primary",
                       bg=th.CARD, font=F["small"], padx=14,
                       pady=5).pack(side="left", padx=6)
        r2 = tk.Frame(a, bg=th.CARD)
        r2.pack(fill="x", pady=(2, 0))
        tk.Label(r2, text="アーティファクトから選ぶ", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left", padx=(0, 6))
        self.v_art = tk.StringVar()
        self.cb_art = ttk.Combobox(r2, textvariable=self.v_art,
                                   state="readonly", width=30,
                                   style="Cute.TCombobox", font=F["ui"])
        self.cb_art["values"] = [tb.artifact_name(en) for en, _ja in tb.ARTIFACTS]
        self.cb_art.pack(side="left")
        th.RoundButton(r2, "これを足す", self.add_artifact, kind="soft",
                       bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left", padx=6)
        tk.Label(a, text="日本語名はゲームによって表記がゆれるので、目安です。"
                         "自分の書き方で足してもらってかまいません",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=760,
                 justify="left").pack(anchor="w", pady=(4, 0))

        # ---- 一覧 ----
        wrap = tk.Frame(self, bg=th.BG)
        wrap.pack(fill="both", expand=True, pady=(8, 0))
        self.canvas = tk.Canvas(wrap, bg=th.BG, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=th.BG)
        self._win = self.canvas.create_window((0, 0), window=self.inner,
                                              anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win, width=e.width))
        self.bind_all("<MouseWheel>", self._wheel, add="+")

        self.refresh_maps()

    # ------------------------------------------------ マップ
    def book(self):
        return self.app.book

    def refresh_maps(self, pick=None):
        names = list(self.book().order)
        self.cb_map["values"] = names
        if pick and pick in names:
            self.map_name = pick
        elif self.map_name not in names:
            self.map_name = names[0] if names else ""
        self.v_map.set(self.map_name)
        self.rebuild()

    def pick_map(self):
        self.map_name = self.v_map.get()
        self.app.cfg["tribute_map"] = self.map_name
        self.rebuild()

    def add_map(self):
        """見張っているマップから選ぶ。無ければ手で書く。"""
        AddMapDialog(self.app, self)

    def drop_map(self):
        if not self.map_name:
            return
        if not self.app.confirm_drop("%s（貢物の控え）" % self.map_name):
            return
        self.book().drop_map(self.map_name)
        self.app.save_book()
        self.map_name = ""
        self.refresh_maps()

    # ------------------------------------------------ 品目
    def _need(self):
        try:
            return max(0, int(float(self.v_need.get())))
        except (TypeError, ValueError):
            return 0

    def add_item(self, name=None, kind=""):
        name = (name if name is not None else self.v_new.get()).strip()
        if not name:
            return
        if not self.map_name:
            self.app.blip("さきにマップを足してください", "warn")
            return
        self.book().put(self.map_name, name, need=self._need(), kind=kind)
        self.book().sort(self.map_name)
        self.app.save_book()
        self.v_new.set("")
        self.rebuild()

    def add_artifact(self):
        got = self.v_art.get().strip()
        if got:
            self.add_item(got, kind="artifact")

    def bump(self, item, d):
        item.add(d)
        self.app.save_book()
        self.rebuild()

    def set_have(self, item, var):
        try:
            item.set_have(int(float(var.get())))
        except (TypeError, ValueError):
            pass
        self.app.save_book()
        self.rebuild()

    def set_need(self, item, var):
        try:
            item.need = max(0, int(float(var.get())))
        except (TypeError, ValueError):
            pass
        self.app.save_book()
        self.rebuild()

    def drop_item(self, item):
        self.book().drop(self.map_name, item)
        self.app.save_book()
        self.rebuild()

    # ------------------------------------------------ 見た目
    def rebuild(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.rows = []
        F = self.F
        if self.map_name:
            self.btn_drop_map.pack(side="left")
        else:
            self.btn_drop_map.pack_forget()
        if not self.map_name:
            self.lbl_sum.config(text="")
            box = tk.Frame(self.inner, bg=th.BG)
            box.pack(fill="x", pady=40)
            tk.Label(box, text="🏺", bg=th.BG, font=(th.JP, 34)).pack()
            tk.Label(box, text="まだマップがありません", bg=th.BG, fg=th.INK,
                     font=F["cute_b"]).pack(pady=(6, 2))
            tk.Label(box, text="上の「＋ マップを足す」から始めてください",
                     bg=th.BG, fg=th.INK_SUB, font=F["small"]).pack()
            return
        self.lbl_sum.config(text=self.book().summary(self.map_name))
        rows = self.book().items(self.map_name)
        if not rows:
            tk.Label(self.inner, text="このマップにはまだ品目がありません",
                     bg=th.BG, fg=th.INK_SUB, font=F["small"]).pack(pady=24)
            return
        for it in rows:
            self._row(it)

    def _row(self, it):
        F = self.F
        card = th.Card(self.inner, bg=th.BG)
        card.pack(fill="x", pady=3)
        b = card.body
        line = tk.Frame(b, bg=th.CARD)
        line.pack(fill="x")

        left, txt = it.short()
        mark = "🏺" if it.kind == "artifact" else "🦴"
        tk.Label(line, text=mark, bg=th.CARD, font=(th.JP, 13)).pack(side="left")
        tk.Label(line, text=it.name, bg=th.CARD, fg=th.INK, font=F["cute"],
                 anchor="w").pack(side="left", padx=(4, 10))
        tk.Label(line, text=txt, bg=th.CARD,
                 fg=th.MINT if (it.need > 0 and left == 0) else th.INK_SUB,
                 font=F["small"]).pack(side="left")

        th.RoundButton(line, "✕", lambda i=it: self.drop_item(i), kind="ghost",
                       bg=th.CARD, font=F["small"], padx=8,
                       pady=3).pack(side="right")
        v_need = tk.StringVar(value=str(it.need))
        e2 = th.soft_entry(line, v_need, width=4)
        e2.pack(side="right", padx=(4, 8), ipady=2)
        e2.bind("<Return>", lambda e, i=it, v=v_need: self.set_need(i, v))
        e2.bind("<FocusOut>", lambda e, i=it, v=v_need: self.set_need(i, v))
        tk.Label(line, text="いる数", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="right")

        th.RoundButton(line, "＋", lambda i=it: self.bump(i, 1), kind="soft",
                       bg=th.CARD, font=F["small"], padx=10,
                       pady=3).pack(side="right", padx=(4, 12))
        v_have = tk.StringVar(value=str(it.have))
        e1 = th.soft_entry(line, v_have, width=4)
        e1.pack(side="right", padx=4, ipady=2)
        e1.bind("<Return>", lambda e, i=it, v=v_have: self.set_have(i, v))
        e1.bind("<FocusOut>", lambda e, i=it, v=v_have: self.set_have(i, v))
        th.RoundButton(line, "－", lambda i=it: self.bump(i, -1), kind="soft",
                       bg=th.CARD, font=F["small"], padx=10,
                       pady=3).pack(side="right")

    def _wheel(self, e):
        try:
            if self.winfo_ismapped():
                self.canvas.yview_scroll(int(-e.delta / 120), "units")
        except tk.TclError:
            pass

    def update_view(self, now=None):
        pass


class AddMapDialog(tk.Toplevel):
    """見張っているマップから選ぶか、名前を書いて足す。"""

    def __init__(self, app, page):
        super().__init__(app)
        self.app, self.page = app, page
        F = app.F
        self.title("マップを足す")
        self.configure(bg=th.BG)
        self.resizable(False, False)
        self.transient(app)
        card = th.Card(self, bg=th.BG)
        card.pack(fill="both", expand=True, padx=10, pady=10)
        c = card.body
        tk.Label(c, text="どのマップ？", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")

        watched = [n for n in app.clocks.order
                   if n not in page.book().maps]
        if watched:
            tk.Label(c, text="見張っているマップから", bg=th.CARD, fg=th.INK_SUB,
                     font=F["small"]).pack(anchor="w", pady=(6, 2))
            for name in watched:
                th.RoundButton(c, gametime_label(name),
                               lambda n=name: self.take(n), kind="soft",
                               bg=th.CARD, font=F["small"], padx=12,
                               pady=5).pack(anchor="w", pady=1)
        tk.Label(c, text="名前を書いて足す", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(anchor="w", pady=(10, 2))
        row = tk.Frame(c, bg=th.CARD)
        row.pack(anchor="w")
        self.v = tk.StringVar()
        e = th.soft_entry(row, self.v, width=22)
        e.pack(side="left", ipady=3)
        e.bind("<Return>", lambda ev: self.take(self.v.get()))
        th.RoundButton(row, "足す", lambda: self.take(self.v.get()),
                       kind="primary", bg=th.CARD, font=F["small"], padx=14,
                       pady=5).pack(side="left", padx=6)
        e.focus_set()

    def take(self, name):
        name = (name or "").strip()
        if not name:
            return
        self.page.book().add_map(name)
        self.app.save_book()
        self.page.refresh_maps(pick=name)
        self.destroy()


def gametime_label(name):
    try:
        import gametime
        return gametime.map_label(name)
    except Exception:
        return name
