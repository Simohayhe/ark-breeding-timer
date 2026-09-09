# -*- coding: utf-8 -*-
"""🏺 貢物とアーティファクトのページ。

マップを選んで、持っている数といる数を並べるだけ。数は ＋/－ で動かす。
スクショからの取り込みは、読めることを確かめてから足す（いまは手入力）。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import hudread
import macro
import theme as th
import tribute as tb
import tribute_read as tr


class Fold(tk.Frame):
    """見出しを押すと開け閉めするひとかたまり。

    貢物の一覧が主役なので、入力まわりは普段たたんでおく。
    """

    def __init__(self, master, title, font, bg=th.CARD, opened=False):
        super().__init__(master, bg=bg)
        self.title = title
        self.opened = bool(opened)
        self.head = tk.Label(self, text="", bg=bg, fg=th.INK, font=font,
                             anchor="w", cursor="hand2")
        self.head.pack(fill="x")
        self.head.bind("<Button-1>", lambda e: self.toggle())
        self.body = tk.Frame(self, bg=bg)
        self._paint()

    def _paint(self):
        self.head.config(text=("▼ " if self.opened else "▶ ") + self.title)
        if self.opened:
            self.body.pack(fill="x", pady=(4, 0))
        else:
            self.body.pack_forget()

    def toggle(self):
        self.opened = not self.opened
        self._paint()


class TributePage(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=th.BG)
        self.app = app
        self.F = app.F
        F = self.F
        self.map_name = ""
        self.rows = []
        self.cards = {}

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
        # ボスと難易度は、いちばんよく触るのでここに置く
        br = tk.Frame(c, bg=th.CARD)
        br.pack(fill="x", pady=(8, 0))
        tk.Label(br, text="ボス", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left", padx=(0, 6))
        self.v_boss = tk.StringVar()
        self.cb_boss = ttk.Combobox(br, textvariable=self.v_boss,
                                    state="readonly", width=26,
                                    style="Cute.TCombobox", font=F["ui"])
        self.cb_boss.pack(side="left")
        self.cb_boss.bind("<<ComboboxSelected>>", lambda e: self.pick_boss())
        self.boss_keys = []
        # 難易度は、ボスを選んでいるときだけ意味がある。
        # 「ぜんぶ」のときは、どの難易度のぶんも出すので隠す。
        self.diff_box = tk.Frame(br, bg=th.CARD)
        self.diff_box.pack(side="left")
        tk.Label(self.diff_box, text="　難易度", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left", padx=(0, 6))
        self.v_diff = tk.StringVar(value=tb.diff_label(
            self.app.cfg.get("tribute_diff") or "B"))
        cbd = ttk.Combobox(self.diff_box, textvariable=self.v_diff,
                           state="readonly", width=10,
                           style="Cute.TCombobox", font=F["ui"])
        cbd["values"] = [lbl for _k, lbl in tb.DIFFS]
        cbd.pack(side="left")
        cbd.bind("<<ComboboxSelected>>", lambda e: self.pick_boss())

        tk.Label(br, text="　並び", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left", padx=(0, 6))
        self.v_sort = tk.StringVar(value=self.sort_label(
            self.app.cfg.get("tribute_sort") or "name"))
        cbs = ttk.Combobox(br, textvariable=self.v_sort, state="readonly",
                           width=18, style="Cute.TCombobox", font=F["ui"])
        cbs["values"] = [lbl for _k, lbl in self.SORTS]
        cbs.pack(side="left")
        cbs.bind("<<ComboboxSelected>>", lambda e: self.pick_sort())

        tk.Label(br, text="　🔍", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left", padx=(0, 4))
        self.v_find = tk.StringVar()
        e_find = th.soft_entry(br, self.v_find, width=16)
        e_find.pack(side="left", ipady=3)
        e_find.bind("<Escape>", lambda e: self.v_find.set(""))
        # 打っている途中で作り直すと重いので、手が止まってから
        self.v_find.trace_add("write", lambda *a: self._find_soon())
        self.btn_clear = th.RoundButton(br, "✕", lambda: self.v_find.set(""),
                                        kind="ghost", bg=th.CARD,
                                        font=F["small"], padx=8, pady=4)

        # 行ってきたら、使ったぶんを引く。押し間違えても戻せるようにする
        self.spend_box = tk.Frame(br, bg=th.CARD)
        self.spend_box.pack(side="left", padx=(12, 0))
        self.btn_spend = th.RoundButton(self.spend_box, "🗡 ボスに行った",
                                        self.spend_boss, kind="primary",
                                        bg=th.CARD, font=F["small"],
                                        padx=16, pady=5)
        self.btn_undo = th.RoundButton(self.spend_box, "🔙 もどす",
                                       self.undo_spend, kind="ghost",
                                       bg=th.CARD, font=F["small"],
                                       padx=12, pady=5)
        self._spent = None

        self.lbl_sum = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="w")
        self.lbl_sum.pack(fill="x", pady=(6, 0))
        self.lbl_short = tk.Label(c, text="", bg=th.CARD, fg=th.PINK_DK,
                                  font=F["cute_b"], anchor="w",
                                  wraplength=900, justify="left")
        self.lbl_short.pack(fill="x", pady=(2, 0))

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


        # ---- 下: 入力まわりは、たたんでおく ----
        under = tk.Frame(self, bg=th.BG)
        under.pack(fill="x", pady=(8, 0))
        self.folds = []
        for name, title, build, opened in (
                ("add", "＋ 品目を足す", self._build_add, False),
                ("auto", "📥 このマップの貢物をまとめて入れる",
                 self._build_auto, False),
                ("cap", "📷 スクショから取り込む", self._build_cap, False)):
            card = th.Card(under, bg=th.BG)
            card.pack(fill="x", pady=(0, 4))
            fold = Fold(card.body, title, F["cute_b"], opened=opened)
            fold.pack(fill="x")
            build(fold.body)
            self.folds.append(fold)

        self.rec = None
        self.show_area()
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
        if hasattr(self, "lbl_auto"):
            self.refresh_bosses()
            self.auto_first_time()
            self.show_auto()

    def pick_map(self):
        self.map_name = self.v_map.get()
        self.app.cfg["tribute_map"] = self.map_name
        self.rebuild()
        self.refresh_bosses()
        self.auto_first_time()
        self.show_auto()

    def auto_first_time(self):
        """まだ何も入っていないマップなら、1度だけ勝手に入れる。

        前のもので作ったマップは空のままなので、開いたときに埋める。
        自分で全部消したあとに勝手に戻ってこないよう、入れたことは覚えておく。
        """
        mp = self.map_name
        if not mp or self.book().items(mp):
            return
        done = self.app.cfg.setdefault("tribute_filled", [])
        if mp in done or not tb.known_map(mp):
            return
        done.append(mp)
        self.fill_from_known(quiet=True)

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
        self.touch(item)

    def set_have(self, item, var):
        try:
            item.set_have(int(float(var.get())))
        except (TypeError, ValueError):
            var.set(str(item.have))     # 読めない字は書き戻す
        self.touch(item)

    def set_need(self, item, var):
        try:
            item.need = max(0, int(float(var.get())))
        except (TypeError, ValueError):
            var.set(str(item.need))
            return self.touch(item)
        got = self.cards.get(id(item))
        if got:
            got["need"] = item.need
        self.touch(item)

    def drop_item(self, item):
        self.book().drop(self.map_name, item)
        self.app.save_book()
        self.rebuild()

    # ------------------------------------------------ 見た目
    COLS = 3          # 一覧を何列に並べるか
    SORTS = (("name", "名前順"),
             ("short", "足りない順"),
             ("kind", "種類順（🏺が先）"),
             ("have", "持っている数が多い順"))

    def _find_soon(self):
        got = getattr(self, "_find_job", None)
        if got is not None:
            try:
                self.after_cancel(got)
            except Exception:
                pass
        self._find_job = self.after(250, self._find_now)

    def _find_now(self):
        self._find_job = None
        self.rebuild()

    def find_text(self):
        return tb.search_key(self.v_find.get())

    def keep(self, rows):
        """検索の字が入っていれば、名前で絞る。

        ひらがなで打っても、ローマ字で打っても当たる。
        """
        want = self.v_find.get()
        if not tb.search_key(want):
            return rows
        return [(it, need) for it, need in rows if tb.hit(want, it.name)]

    def sort_label(self, key):
        for k, lbl in self.SORTS:
            if k == key:
                return lbl
        return self.SORTS[0][1]

    def sort_key(self):
        want = self.v_sort.get()
        for k, lbl in self.SORTS:
            if lbl == want:
                return k
        return "name"

    def pick_sort(self):
        """並び順を変えた。ここでだけ並べ直す。"""
        self.app.cfg["tribute_sort"] = self.sort_key()
        self.rebuild()

    def sorted_rows(self, rows):
        """選ばれた並び順で。数をいじったときは並べ直さない。"""
        how = self.sort_key()
        if how == "short":
            rows.sort(key=lambda r: (
                -(max(0, r[1] - r[0].have)), r[0].name))
        elif how == "kind":
            rows.sort(key=lambda r: (0 if r[0].kind == "artifact" else 1,
                                     r[0].name))
        elif how == "have":
            rows.sort(key=lambda r: (-r[0].have, r[0].name))
        else:
            rows.sort(key=lambda r: r[0].name)
        return rows

    def view_rows(self):
        """いま出すもの。[(品目, いる数)]。

        持っている数はマップごとに覚えたもの。いる数は、選んだボスと
        難易度から出す（ボスによって違うので、覚えたりはしない）。

        「ぜんぶ」は、そのマップに要るものを**データから**ぜんぶ出す。
        帳面にあるものだけを並べていたころは、前にベータで作った帳面に
        アルファぶんが入っておらず、一覧から抜けていた。
        手で足したものやスクショから取り込んだものは、後ろに足す。
        """
        mp = self.map_name
        if not mp:
            return []
        boss = self.boss_key()
        # 「ぜんぶ」は、どの難易度のぶんも出す（diff=None）
        diff = None if boss == tb.ALL_BOSSES else self.diff_key()
        want = tb.known_items(mp, diff, boss)
        out, seen, added = [], set(), False
        for name, need, kind in want:
            it = self.book().find(mp, name)
            if it is None:          # まだ帳面に無ければ、0個として作る
                it = self.book().put(mp, name, kind=kind)
                added = True
            out.append((it, need))
            seen.add(id(it))
        if boss == tb.ALL_BOSSES:
            for it in self.book().items(mp):
                if id(it) not in seen:
                    out.append((it, it.need))
        if added:
            self.book().sort(mp)
            self.app.save_book()
        return out

    def rebuild(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.rows = []
        self.cards = {}
        F = self.F
        if self.map_name:
            self.btn_drop_map.pack(side="left")
        else:
            self.btn_drop_map.pack_forget()
        if not self.map_name:
            self.lbl_sum.config(text="")
            self.lbl_short.config(text="")
            box = tk.Frame(self.inner, bg=th.BG)
            box.grid(row=0, column=0, sticky="ew", pady=40)
            self.inner.columnconfigure(0, weight=1)
            tk.Label(box, text="🏺", bg=th.BG, font=(th.JP, 34)).pack()
            tk.Label(box, text="まだマップがありません", bg=th.BG, fg=th.INK,
                     font=F["cute_b"]).pack(pady=(6, 2))
            tk.Label(box, text="上の「＋ マップを足す」から始めてください",
                     bg=th.BG, fg=th.INK_SUB, font=F["small"]).pack()
            return

        allrows = self.view_rows()
        rows = self.keep(allrows)
        self.head_text(allrows, len(rows))
        if self.find_text():
            self.btn_clear.pack(side="left", padx=(2, 0))
        else:
            self.btn_clear.pack_forget()
        if not rows:
            tk.Label(self.inner,
                     text=("「%s」に当たるものがありません" % self.v_find.get()
                           if self.find_text() else "出すものがありません"),
                     bg=th.BG, fg=th.INK_SUB, font=F["small"]).grid(
                         row=0, column=0, pady=24)
            self.inner.columnconfigure(0, weight=1)
            self.sync_diff()
            self.sync_spend()
            return
        # 並べ直すのはここだけ。数をいじるたびに並べ替えると、
        # 押した札が目の前から飛んでいって「消えた」ように見える。
        self.sorted_rows(rows)
        for c in range(self.COLS):
            self.inner.columnconfigure(c, weight=1, uniform="trib")
        for n, (it, need) in enumerate(rows):
            self._row(it, need, n // self.COLS, n % self.COLS)
        self.sync_diff()
        self.sync_spend()

    def _paint_row(self, it):
        """その札の「あと何個」と色だけを塗り直す。"""
        got = self.cards.get(id(it))
        if not got:
            return
        need = got["need"]
        left = max(0, need - it.have) if need > 0 else 0
        try:
            got["have"].set(str(it.have))
            got["name"].config(fg=th.PINK_DK if left else th.INK)
            if left:
                got["left"].config(text="あと%d" % left, fg=th.PINK_DK)
            elif need > 0:
                got["left"].config(text="✔", fg=th.MINT)
            else:
                got["left"].config(text="")
        except tk.TclError:
            pass

    def touch(self, it):
        """数が変わった。その札と、上の見出しだけを直す。

        一覧ごと作り直すと、押した札が動いたり、下まで見ていた場所が
        戻ったりする。数をいじるだけなら、そこだけ直せばよい。
        並べ直すのは、並び順を選んだときと、マップやボスを変えたとき。
        """
        self.app.save_book()
        self._paint_row(it)
        rows = self.view_rows()
        self.head_text(rows, len(self.keep(rows)))
        self.sync_spend()

    def head_text(self, rows, showing=None):
        """上の2行。なにを出しているかと、あと何が足りないか。

        showing を渡すと、検索で絞ったあと何件出ているかも書く。
        足りない数は、絞る前のぜんぶで数える（絞って減ったように
        見えると、そろったのかと勘違いする）。
        """
        boss = self.boss_key()
        who = ("このマップの貢物ぜんぶ" if boss == tb.ALL_BOSSES
               else "%s（%s）に挑むのに要るもの"
                    % (self.v_boss.get(), tb.diff_label(self.diff_key())))
        art = sum(1 for it, _n in rows if it.kind == "artifact")
        head = "%s … %d品目（うちアーティファクト %d）" % (who, len(rows), art)
        if showing is not None and showing != len(rows):
            head += "　🔍「%s」に当たる %d件を出しています" % (
                self.v_find.get().strip(), showing)
        self.lbl_sum.config(text=head)
        short = [(it, need - it.have) for it, need in rows
                 if need > 0 and it.have < need]
        if not short:
            if any(need > 0 for _it, need in rows):
                self.lbl_short.config(text="✔ ぜんぶそろっています", fg=th.MINT)
            else:
                self.lbl_short.config(text="")
            return
        total = sum(n for _it, n in short)
        head = "⚠ あと %d品目 ／ 合計 %d個 たりません　" % (len(short), total)
        names = "、".join("%s あと%d" % (it.name, n) for it, n in short[:6])
        if len(short) > 6:
            names += " ほか%d件" % (len(short) - 6)
        self.lbl_short.config(text=head + names, fg=th.PINK_DK)

    def _row(self, it, need, row, col):
        """品目ひとつぶんの札。狭いので、名前と数を2段に分ける。"""
        F = self.F
        left = max(0, need - it.have) if need > 0 else 0
        card = th.Card(self.inner, bg=th.BG)
        card.grid(row=row, column=col, sticky="nsew", padx=3, pady=3)
        b = card.body

        top = tk.Frame(b, bg=th.CARD)
        top.pack(fill="x")
        mark = "🏺" if it.kind == "artifact" else "🦴"
        tk.Label(top, text=mark, bg=th.CARD, font=(th.JP, 11)).pack(side="left")
        lbl_name = tk.Label(top, text=it.name, bg=th.CARD,
                            fg=th.PINK_DK if left else th.INK, font=F["cute"],
                            anchor="w", justify="left", wraplength=180)
        lbl_name.pack(side="left", padx=(3, 0))
        th.RoundButton(top, "✕", lambda i=it: self.drop_item(i), kind="ghost",
                       bg=th.CARD, font=F["small"], padx=6,
                       pady=2).pack(side="right")

        line = tk.Frame(b, bg=th.CARD)
        line.pack(fill="x", pady=(4, 0))
        th.RoundButton(line, "－", lambda i=it: self.bump(i, -1), kind="soft",
                       bg=th.CARD, font=F["small"], padx=8,
                       pady=2).pack(side="left")
        v_have = tk.StringVar(value=str(it.have))
        e1 = th.soft_entry(line, v_have, width=4)
        e1.pack(side="left", padx=3, ipady=1)
        e1.bind("<Return>", lambda e, i=it, v=v_have: self.set_have(i, v))
        e1.bind("<FocusOut>", lambda e, i=it, v=v_have: self.set_have(i, v))
        th.RoundButton(line, "＋", lambda i=it: self.bump(i, 1), kind="soft",
                       bg=th.CARD, font=F["small"], padx=8,
                       pady=2).pack(side="left")

        if self.boss_key() != tb.ALL_BOSSES:
            # ボスを選んでいるときの「いる数」は、そのボスのぶん。書き換えない
            tk.Label(line, text=" / %d" % need, bg=th.CARD, fg=th.INK_SUB,
                     font=F["small"]).pack(side="left")
        else:
            tk.Label(line, text=" / ", bg=th.CARD, fg=th.INK_SUB,
                     font=F["small"]).pack(side="left")
            v_need = tk.StringVar(value=str(need))
            e2 = th.soft_entry(line, v_need, width=4)
            e2.pack(side="left", ipady=1)
            e2.bind("<Return>", lambda e, i=it, v=v_need: self.set_need(i, v))
            e2.bind("<FocusOut>", lambda e, i=it, v=v_need: self.set_need(i, v))
        lbl_left = tk.Label(line, text="", bg=th.CARD, font=F["cute"])
        lbl_left.pack(side="left", padx=(5, 0))
        self.cards[id(it)] = {"need": need, "name": lbl_name,
                              "left": lbl_left, "have": v_have}
        self._paint_row(it)

    # ------------------------------------------------ 行ってきた
    def sync_diff(self):
        """難易度の欄の出し入れ。ボスを選んでいるときだけ出す。"""
        if self.boss_key() == tb.ALL_BOSSES:
            self.diff_box.pack_forget()
        else:
            self.diff_box.pack(side="left", before=self.spend_box)

    def sync_spend(self):
        """「行った」ボタンの出し入れ。ボスを選んでいるときだけ出す。"""
        boss = self.boss_key() if self.map_name else tb.ALL_BOSSES
        if self.map_name and boss != tb.ALL_BOSSES and self.view_rows():
            self.btn_spend.pack(side="left")
        else:
            self.btn_spend.pack_forget()
        if self._spent:
            self.btn_undo.pack(side="left", padx=(4, 0))
        else:
            self.btn_undo.pack_forget()

    def spend_boss(self):
        """挑みに行ったぶんを、持ち物から引く。

        足りないものは、あるだけ引く（マイナスにはしない）。
        引いた中身は覚えておいて、押し間違えたら戻せるようにする。
        """
        rows = self.view_rows()
        if not rows:
            return
        spent, short = [], []
        for it, need in rows:
            if need <= 0:
                continue
            take = min(it.have, need)
            if take:
                it.set_have(it.have - take)
                spent.append((it, take))
            if need > take:
                short.append((it.name, need - take))
        if not spent and not short:
            return
        self._spent = spent
        self.app.save_book()
        self.rebuild()
        who = "%s（%s）" % (self.v_boss.get(), tb.diff_label(self.diff_key()))
        msg = "🗡 %s に行きました。%d品目を引きました" % (who, len(spent))
        if short:
            msg += "　⚠ 足りなかったぶん: " + "、".join(
                "%s %d" % (n, c) for n, c in short[:5])
            if len(short) > 5:
                msg += " ほか%d件" % (len(short) - 5)
        self.lbl_short.config(text=msg, fg=th.PINK_DK if short else th.MINT)
        self.sync_spend()

    def undo_spend(self):
        """引いたぶんを戻す。"""
        if not self._spent:
            return
        for it, take in self._spent:
            it.set_have(it.have + take)
        n = len(self._spent)
        self._spent = None
        self.app.save_book()
        self.rebuild()
        self.lbl_short.config(text="🔙 %d品目を戻しました" % n, fg=th.INK_SUB)
        self.sync_spend()

    # ------------------------------------------------ まとめて入れる
    def diff_key(self):
        want = self.v_diff.get()
        for k, lbl in tb.DIFFS:
            if lbl == want:
                return k
        return "B"

    def refresh_bosses(self):
        """このマップのボスを、選べるように並べる。"""
        got = tb.known_bosses(self.map_name)
        self.boss_keys = [tb.ALL_BOSSES] + [key for _lbl, key in got]
        labels = ["ぜんぶ（%d体）" % len(got) if got else "ぜんぶ"] \
            + [lbl for lbl, _key in got]
        self.cb_boss["values"] = labels
        want = self.app.cfg.get("tribute_boss") or tb.ALL_BOSSES
        i = self.boss_keys.index(want) if want in self.boss_keys else 0
        self.cb_boss.current(i)

    def pick_boss(self):
        """ボスや難易度を選び直した。出すものを入れ替える。"""
        self.app.cfg["tribute_diff"] = self.diff_key()
        self.app.cfg["tribute_boss"] = self.boss_key()
        self._spent = None          # 別の話になるので、戻せるのはここまで
        self.rebuild()
        self.show_auto()

    def boss_key(self):
        i = self.cb_boss.current()
        if 0 <= i < len(self.boss_keys):
            return self.boss_keys[i]
        return tb.ALL_BOSSES

    def show_auto(self):
        """このマップのぶんが用意されているかを出す。"""
        self.app.cfg["tribute_diff"] = self.diff_key()
        self.app.cfg["tribute_boss"] = self.boss_key()
        if not self.map_name:
            self.lbl_auto.config(text="", fg=th.INK_SUB)
            return
        boss = self.boss_key()
        rows = tb.known_items(self.map_name, self.diff_key(), boss)
        if not rows:
            if tb.known_map(self.map_name):
                self.lbl_auto.config(
                    text="この難易度で要るものがありません", fg=th.INK_SUB)
            else:
                self.lbl_auto.config(
                    text="「%s」の貢物は用意がありません。"
                         "名前をゲームと同じ英語名（Ragnarok など）にすると"
                         "見つかることがあります" % self.map_name,
                    fg=th.PINK_DK)
            return
        art = sum(1 for _n, _c, k in rows if k == "artifact")
        who = "ボスぜんぶ" if boss == tb.ALL_BOSSES else self.v_boss.get()
        self.lbl_auto.config(
            text="%s の %s（%s） … %d品目（うちアーティファクト %d）"
                 "　出どころ: %s"
                 % (self.map_name, who, tb.diff_label(self.diff_key()),
                    len(rows), art, tb.known_src(self.map_name) or "?"),
            fg=th.INK_SUB)

    def fill_from_known(self, quiet=False):
        """一覧から、このマップの貢物を入れる。持っている数は触らない。"""
        if not self.map_name:
            self.lbl_auto.config(text="さきにマップを足してください",
                                 fg=th.PINK_DK)
            return
        boss = self.boss_key()
        rows = tb.known_items(
            self.map_name, None if boss == tb.ALL_BOSSES else self.diff_key(),
            boss)
        if not rows:
            self.show_auto()
            return
        added = 0
        for name, need, kind in rows:
            if self.book().find(self.map_name, name) is None:
                added += 1
            self.book().put(self.map_name, name, need=need, kind=kind)
        self.book().sort(self.map_name)
        self.app.save_book()
        self.rebuild()
        self.lbl_auto.config(
            text="%d品目を入れました（新しく増えたのは %d）"
                 % (len(rows), added), fg=th.MINT)
        if quiet:
            self.show_auto()        # 足したときは、ふつうの案内に戻しておく

    # ------------------------------------------------ スクショ
    def area(self):
        got = self.app.cfg.get("tribute_rect")
        if got and len(got) == 4 and got[2] > 20 and got[3] > 20:
            return [int(v) for v in got]
        return None

    def show_area(self, msg=None, warn=False):
        if msg is None:
            r = self.area()
            msg = ("いまの範囲: 左%d 上%d ／ %d×%d" % tuple(r) if r
                   else "まだ範囲を教わっていません")
        self.lbl_cap.config(text=msg, fg=th.PINK_DK if warn else th.INK_SUB)

    def learn_area(self):
        """箱の中身が出ている所を、左上と右下のクリックで教えてもらう。"""
        if self.rec is not None:
            self.rec.stop()
            self.rec = None
            self.btn_area.set_text("🖱 範囲をおしえる")
            self.show_area("やめました")
            return
        self.rec = macro.ClickRecorder(2)
        self.rec.start()
        self.btn_area.set_text("やめる")
        self.show_area("ARKへ行って、品名が並んでいる所の「左上」→「右下」の順に"
                       "クリックしてください")
        self._poll_area()

    def _poll_area(self):
        rec = self.rec
        if rec is None:
            return
        if rec.done and len(rec.points) >= 2:
            self.rec = None
            self.btn_area.set_text("🖱 範囲をおしえなおす")
            (x1, y1), (x2, y2) = rec.points[0], rec.points[1]
            left, top = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)
            if w < 40 or h < 40:
                self.show_area("範囲が小さすぎます。もう一度おしえてください",
                               warn=True)
                return
            self.app.cfg["tribute_rect"] = [left, top, w, h]
            self.app.save_cfg()
            self.show_area()
            return
        self.after(150, self._poll_area)

    def read_now(self):
        if not self.map_name:
            self.show_area("さきにマップを足してください", warn=True)
            return
        r = self.area()
        if not r:
            self.show_area("さきに範囲をおしえてください", warn=True)
            return
        self.btn_read.set_text("読んでいます…")
        self.show_area("読んでいます。少しかかります…")
        self.after(60, lambda: self._read_go(r))

    def _read_go(self, r):
        try:
            boxes, rows, used = tr.read_area(r)
        except hudread.HudError as e:
            self.btn_read.set_text("📷 いま読む")
            self.show_area("読めませんでした（%s）" % e, warn=True)
            return
        except Exception as e:                     # 予想外でも画面は戻す
            self.btn_read.set_text("📷 いま読む")
            self.show_area("読めませんでした（%s）" % e, warn=True)
            return
        self.btn_read.set_text("📷 いま読む")
        if not rows:
            self.show_area("品名を1つも取れませんでした。範囲と、品名が出る"
                           "表示になっているかを確かめてください", warn=True)
            return
        self.show_area("%d品目を読みました" % len(rows))
        ImportDialog(self.app, self, rows, used, len(boxes))

    def _build_add(self, parent):
        F = self.F
        # ---- 足す ----
        a = parent
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


    def _build_auto(self, parent):
        F = self.F
        # ---- まとめて入れる ----
        u = parent
        tk.Label(u, text="そのマップのボスに要るものが、いる数つきで入ります。"
                         "持っている数はそのままです",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=760,
                 justify="left").pack(anchor="w", pady=(0, 6))
        ar = tk.Frame(u, bg=th.CARD)
        ar.pack(fill="x")
        self.btn_auto = th.RoundButton(ar, "📥 このマップのぶんを入れる",
                                       self.fill_from_known, kind="primary",
                                       bg=th.CARD, font=F["small"],
                                       padx=16, pady=5)
        self.btn_auto.pack(side="left")
        self.lbl_auto = tk.Label(u, text="", bg=th.CARD, fg=th.INK_SUB,
                                 font=F["small"], anchor="w", wraplength=760,
                                 justify="left")
        self.lbl_auto.pack(fill="x", pady=(4, 0))


    def _build_cap(self, parent):
        F = self.F
        # ---- スクショから ----
        p = parent
        tk.Label(p, text="ARKで箱を開けて、品名が出る表示にしてから範囲をおしえて"
                         "ください。読んだ結果は、入れる前に確かめられます",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=760,
                 justify="left").pack(anchor="w", pady=(0, 6))
        cr = tk.Frame(p, bg=th.CARD)
        cr.pack(fill="x")
        self.btn_area = th.RoundButton(cr, "🖱 範囲をおしえる", self.learn_area,
                                       kind="soft", bg=th.CARD,
                                       font=F["small"], padx=14, pady=5,
                                       width=180)
        self.btn_area.pack(side="left")
        self.btn_read = th.RoundButton(cr, "📷 いま読む", self.read_now,
                                       kind="primary", bg=th.CARD,
                                       font=F["small"], padx=14, pady=5)
        self.btn_read.pack(side="left", padx=6)
        self.lbl_cap = tk.Label(p, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="w", wraplength=760,
                                justify="left")
        self.lbl_cap.pack(fill="x", pady=(4, 0))
        self.rec = None
        self.show_area()


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
        page = self.page
        page.book().add_map(name)
        self.app.save_book()
        page.refresh_maps(pick=name)
        self.destroy()
        # 用意のあるマップなら、貢物とアーティファクトをそのまま入れておく。
        # 足したそばから空の一覧を見せても、やることが増えるだけ。
        if tb.known_map(name):
            page.fill_from_known(quiet=True)


def gametime_label(name):
    try:
        import gametime
        return gametime.map_label(name)
    except Exception:
        return name


class ImportDialog(tk.Toplevel):
    """スクショから読んだ結果を見せて、直してから入れてもらう窓。

    誤読を黙って持ち物帳に書き込むほうが、読めないより始末が悪い。
    かならず目を通せる形にしておく。
    """

    def __init__(self, app, page, rows, used=None, count=0):
        super().__init__(app)
        self.app, self.page = app, page
        F = app.F
        self.title("スクショから取り込む")
        self.configure(bg=th.BG)
        self.transient(app)
        self.geometry("640x620")
        self.vars = []

        card = th.Card(self, bg=th.BG)
        card.pack(fill="both", expand=True, padx=10, pady=10)
        c = card.body
        tk.Label(c, text="読めたもの", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        note = "%d品目（文字 %d個から）" % (len(rows), count)
        if used:
            note += "　濃さ%d・拡大%d倍" % used
        tk.Label(c, text=note + "　✔ の付いたものだけ入ります。名前も数も直せます",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=580,
                 justify="left").pack(anchor="w", pady=(0, 6))

        wrap = tk.Frame(c, bg=th.CARD)
        wrap.pack(fill="both", expand=True)
        cv = tk.Canvas(wrap, bg=th.CARD, highlightthickness=0, bd=0, height=380)
        cv.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=cv.yview)
        sb.pack(side="right", fill="y")
        cv.configure(yscrollcommand=sb.set)
        box = tk.Frame(cv, bg=th.CARD)
        win = cv.create_window((0, 0), window=box, anchor="nw")
        box.bind("<Configure>",
                 lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))

        known = {i.name for i in page.book().items(page.map_name)}
        for name, n in rows:
            fixed, hit = tr.snap(name, known)
            self._row(box, fixed, n, hit)

        bar = tk.Frame(c, bg=th.CARD)
        bar.pack(fill="x", pady=(8, 0))
        th.RoundButton(bar, "この数にする", lambda: self.apply("set"),
                       kind="primary", bg=th.CARD, font=F["cute"],
                       padx=18).pack(side="left")
        th.RoundButton(bar, "いまの数に足す", lambda: self.apply("add"),
                       kind="soft", bg=th.CARD, font=F["cute"],
                       padx=18).pack(side="left", padx=8)
        th.RoundButton(bar, "やめる", self.destroy, kind="ghost", bg=th.CARD,
                       font=F["cute"], padx=14).pack(side="right")
        tk.Label(c, text="「この数にする」は、スクショのとおりに置きかえます。"
                         "箱を1つずつ写して足していくときは「足す」を使ってください",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=580,
                 justify="left").pack(anchor="w", pady=(6, 0))

    def _row(self, box, name, n, hit):
        F = self.app.F
        row = tk.Frame(box, bg=th.CARD)
        row.pack(fill="x", pady=1)
        v_on = tk.BooleanVar(value=True)
        tk.Checkbutton(row, variable=v_on, bg=th.CARD, activebackground=th.CARD,
                       selectcolor=th.FIELD, bd=0,
                       highlightthickness=0).pack(side="left")
        v_name = tk.StringVar(value=name)
        th.soft_entry(row, v_name, width=30).pack(side="left", ipady=2)
        tk.Label(row, text="  ×", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")
        v_n = tk.StringVar(value=str(n))
        th.soft_entry(row, v_n, width=6).pack(side="left", padx=4, ipady=2)
        tk.Label(row, text="  もとからある品目に寄せました" if hit else "",
                 bg=th.CARD, fg=th.MINT, font=F["small"]).pack(side="left")
        self.vars.append((v_on, v_name, v_n))

    def apply(self, how):
        book, mp = self.page.book(), self.page.map_name
        done = 0
        for v_on, v_name, v_n in self.vars:
            if not v_on.get():
                continue
            name = v_name.get().strip()
            if not name:
                continue
            try:
                n = max(0, int(float(v_n.get())))
            except (TypeError, ValueError):
                continue
            if how == "add":
                book.put(mp, name, add=n)
            else:
                book.put(mp, name, have=n)
            done += 1
        book.sort(mp)
        self.app.save_book()
        self.page.rebuild()
        self.app.blip("🏺 %d品目を取り込みました" % done, "mint")
        self.destroy()
