# -*- coding: utf-8 -*-
"""🌙 ゲーム内時計のページ（マップごと）。

ARK は「今の時刻を返す」RCONコマンドを持っていないので、他人のサーバーから
時刻を取ることはできない。そこで、ゲーム内のHUD（Hキー）で読んだ時刻を
1回入れてもらい、あとは実時間から計算して進める。

ズレる原因は主に「サーバーが落ちていた時間」。ゲーム内時間はサーバーが動いて
いる間しか進まないので、A2S で死活を見張って、落ちている間は時計を止める。
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

import gametime as G
import serverwatch as W
import theme as th


def _hms(sec):
    sec = int(max(0, sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)


class Fold(tk.Frame):
    """見出しを押すと開け閉めするひとかたまり。

    ゲーム内時計は設定項目が多くて、全部出しっぱなしだと画面がうるさい。
    普段さわらないものは閉じておいて、必要なときだけ開く。
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
            self.body.pack(fill="x", pady=(2, 0))
        else:
            self.body.pack_forget()

    def set_title(self, title):
        self.title = title
        self._paint()

    def toggle(self):
        self.opened = not self.opened
        self._paint()


class GameTimePage(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=th.BG)
        self.app = app
        self._loading = False
        self._total_msg_until = 0.0   # ①の一言をいつまで出しておくか
        self._poke_at = 0.0           # 「いま見に行く」を押した時刻
        self.meter = None
        self.meter_phase = None
        F = app.F

        # 中身が縦に長いので、ページごとスクロールできるようにする。
        # （「マップを探す」が画面の下に隠れて押せなかった）
        self.canvas = tk.Canvas(self, bg=th.BG, highlightthickness=0, bd=0)
        vs = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                           style="Cute.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=th.BG)
        self._win = self.canvas.create_window((0, 0), window=self.inner,
                                              anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win, width=e.width))

        # ---- 上: マップ（プルダウンで開く） ----
        top = th.Card(self.inner, bg=th.BG)
        top.pack(fill="x")
        b = top.body
        head = tk.Frame(b, bg=th.CARD)
        head.pack(fill="x")
        self.btn_maps = th.RoundButton(head, "🗺 マップ ▾", self.toggle_maps,
                                       kind="primary", bg=th.CARD,
                                       font=F["cute"], padx=14, pady=6,
                                       width=230)
        self.btn_maps.pack(side="left")
        self.lbl_now = tk.Label(head, text="", bg=th.CARD, fg=th.INK,
                                font=F["ui"], anchor="w")
        self.lbl_now.pack(side="left", padx=10)

        self.maps_open = False
        self.maps_box = tk.Frame(b, bg=th.CARD)
        self.rows_box = tk.Frame(self.maps_box, bg=th.CARD)
        self.rows_box.pack(fill="x")
        self.rows = {}

        addb = tk.Frame(self.maps_box, bg=th.CARD)
        addb.pack(fill="x", pady=(10, 0))
        tk.Label(addb, text="サーバーの名前かIPで探して、一覧に追加できます"
                            "（例: GorillaARK ／ 111.237.115.78）",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w")
        brow = tk.Frame(addb, bg=th.CARD)
        brow.pack(fill="x", pady=(2, 0))
        self.v_bulk = tk.StringVar()
        be = th.soft_entry(brow, self.v_bulk, width=22)
        be.pack(side="left", ipady=3)
        be.bind("<Return>", lambda e: self.search_servers())
        th.RoundButton(brow, "🔍 さがす", self.search_servers, kind="accent",
                       bg=th.CARD, font=F["small"], padx=14,
                       pady=6).pack(side="left", padx=6)
        self.lbl_bulk = tk.Label(brow, text="", bg=th.CARD, fg=th.INK_SUB,
                                 font=F["small"])
        self.lbl_bulk.pack(side="left")
        self.found_box = tk.Frame(addb, bg=th.CARD)
        self.found_box.pack(fill="x")
        self.found = []

        nrow = tk.Frame(addb, bg=th.CARD)
        nrow.pack(fill="x", pady=(4, 0))
        tk.Label(nrow, text="名前だけで足す", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left", padx=(0, 6))
        self.v_new = tk.StringVar()
        ent = th.soft_entry(nrow, self.v_new, width=16)
        ent.pack(side="left", ipady=3)
        ent.bind("<Return>", lambda e: self.add_map())
        th.RoundButton(nrow, "＋ 追加", self.add_map, kind="soft", bg=th.CARD,
                       font=F["small"], padx=12, pady=5).pack(side="left",
                                                              padx=6)

        # ---- 中: サーバーの様子 ----
        # 見張っているマップの生死・人数・Day をまとめて出す。
        # 数が多いと画面がうるさいので、たたんでおいて見出しに要約を出す。
        stat = th.Card(self.inner, bg=th.BG)
        stat.pack(fill="x", pady=(8, 0))
        self.fold_stat = Fold(stat.body, "サーバーの様子", F["cute_b"])
        self.fold_stat.pack(fill="x")
        srow = tk.Frame(self.fold_stat.body, bg=th.CARD)
        srow.pack(fill="x", pady=(0, 4))
        th.RoundButton(srow, "↻ いま見に行く", self.poke_watch, kind="soft",
                       bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left")
        self.lbl_poke = tk.Label(srow, text="", bg=th.CARD, fg=th.INK_SUB,
                                 font=F["small"])
        self.lbl_poke.pack(side="left")
        tk.Label(self.fold_stat.body, text="🔔 を押したマップだけ、落ちたときと"
                                           "戻ったときにタイマーと同じように知らせます",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=740,
                 justify="left").pack(anchor="w", pady=(0, 2))
        self.stat_box = tk.Frame(self.fold_stat.body, bg=th.CARD)
        self.stat_box.pack(fill="x")
        self.stat_rows = {}

        # ---- 下: 選んだマップの設定 ----
        conf = th.Card(self.inner, bg=th.BG)
        conf.pack(fill="x", pady=(8, 0))
        c = conf.body
        self.lbl_sel = tk.Label(c, text="", bg=th.CARD, fg=th.INK,
                                font=F["cute_b"], anchor="w")
        self.lbl_sel.pack(fill="x")

        tk.Label(c, text="ゲーム内で H キーを押すと出る時刻を入れてください",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w",
                                                                  pady=(2, 4))
        r1 = tk.Frame(c, bg=th.CARD)
        r1.pack(fill="x", pady=(0, 4))
        self.v_time = tk.StringVar()
        e = th.soft_entry(r1, self.v_time, width=9,
                          font=("Segoe UI Semibold", 16))
        e.pack(side="left", ipady=3)
        e.bind("<Return>", lambda ev: self.do_sync())
        th.RoundButton(r1, "この時刻に合わせる", self.do_sync, kind="primary",
                       bg=th.CARD, font=F["small"], padx=14,
                       pady=6).pack(side="left", padx=8)
        th.RoundButton(r1, "🌙 夜を知らせる", lambda: self.make_timer("night"),
                       kind="accent", bg=th.CARD, font=F["small"], padx=12,
                       pady=6).pack(side="left")
        th.RoundButton(r1, "☀ 朝を知らせる", lambda: self.make_timer("day"),
                       kind="soft", bg=th.CARD, font=F["small"], padx=12,
                       pady=6).pack(side="left", padx=6)
        r2 = tk.Frame(c, bg=th.CARD)
        r2.pack(fill="x", pady=(4, 0))
        tk.Label(r2, text="ゲーム内", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        self.v_at = tk.StringVar(value="20:00")
        at = th.soft_entry(r2, self.v_at, width=8,
                           font=("Segoe UI Semibold", 15))
        at.pack(side="left", padx=4, ipady=2)
        at.bind("<Return>", lambda ev: self.make_at_timer())
        tk.Label(r2, text="になったら", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        th.RoundButton(r2, "⏰ 知らせる", self.make_at_timer, kind="mint",
                       bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left", padx=8)
        for q in ("18:00", "20:00", "22:00", "00:00", "04:00"):
            th.Chip(r2, q, lambda v=q: self.v_at.set(v), bg=th.CARD,
                    font=F["small"]).pack(side="left", padx=2)

        self.lbl_msg = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="w", justify="left",
                                wraplength=740)
        self.lbl_msg.pack(fill="x", pady=(4, 0))

        self.fold_speed = Fold(c, "進む速さ（1日 → 昼か夜を実測 → 残りを逆算）",
                               F["cute_b"])
        self.fold_speed.pack(fill="x", pady=(10, 0))
        cs_ = self.fold_speed.body
        tk.Label(cs_, text="ARKの昼は 05:15〜20:25、夜は 20:25〜05:15 で半分ずつでは"
                           "ありません。1日の長さが分かっていれば、昼か夜のどちらか"
                           "だけ測れば逆側は引き算で出ます",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=740,
                 justify="left").pack(anchor="w", pady=(0, 6))

        # ① 1日の長さ
        s1 = tk.Frame(cs_, bg=th.CARD)
        s1.pack(fill="x")
        tk.Label(s1, text="① 1日の長さ", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(side="left")
        self.v_total = tk.StringVar()
        et = th.soft_entry(s1, self.v_total, width=6)
        et.pack(side="left", padx=6, ipady=3)
        et.bind("<Return>", lambda ev: self.apply_total())
        tk.Label(s1, text="分", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        th.RoundButton(s1, "決定", self.apply_total, kind="soft", bg=th.CARD,
                       font=F["small"], padx=12, pady=5).pack(side="left", padx=8)
        th.RoundButton(s1, "⏱ 自動で測る", self.measure_one, kind="mint",
                       bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left")
        th.RoundButton(s1, "⏱ まとめて測る", self.toggle_bulk_measure,
                       kind="accent", bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left", padx=6)
        self.lbl_total = tk.Label(cs_, text="", bg=th.CARD, fg=th.INK_SUB,
                                  font=F["small"], anchor="w", justify="left",
                                  wraplength=740)
        self.lbl_total.pack(fill="x", pady=(2, 0))

        # 「まとめて測る」で開く、どのマップを測るかの選び場
        self.bulk_open = False
        self.bulk_box = tk.Frame(cs_, bg=th.CARD)
        self.bulk_rows = tk.Frame(self.bulk_box, bg=th.CARD)
        self.bulk_rows.pack(fill="x")
        self.bulk_vars = {}
        bb = tk.Frame(self.bulk_box, bg=th.CARD)
        bb.pack(fill="x", pady=(4, 0))
        th.RoundButton(bb, "▶ 選んだマップを測る", self.measure_selected,
                       kind="primary", bg=th.CARD, font=F["small"], padx=14,
                       pady=6).pack(side="left")
        th.RoundButton(bb, "全部えらぶ", lambda: self._bulk_all(True),
                       kind="soft", bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left", padx=6)
        th.RoundButton(bb, "ぜんぶ外す", lambda: self._bulk_all(False),
                       kind="ghost", bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left")

        # ② 昼か夜を実測
        mt = tk.Frame(cs_, bg=th.CARD)
        mt.pack(fill="x", pady=(8, 0))
        self._bulk_anchor = mt      # まとめて測る欄はこの手前に出す
        tk.Label(mt, text="② 測るのは", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(side="left")
        self.v_phase = tk.StringVar(value="auto")
        for txt, val in (("いま居るほう", "auto"), ("昼", "day"), ("夜", "night")):
            tk.Radiobutton(mt, text=txt, variable=self.v_phase, value=val,
                           bg=th.CARD, fg=th.INK, activebackground=th.CARD,
                           activeforeground=th.INK, selectcolor=th.FIELD,
                           font=F["small"], bd=0,
                           highlightthickness=0).pack(side="left", padx=(6, 0))
        tk.Label(mt, text="／ 何ゲーム内分ごとに押す", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left", padx=(8, 2))
        self.v_step = tk.StringVar(value="1")
        th.soft_entry(mt, self.v_step, width=4).pack(side="left", ipady=2)

        mt2 = tk.Frame(cs_, bg=th.CARD)
        mt2.pack(fill="x", pady=(4, 0))
        self.btn_meter = th.RoundButton(mt2, "⏱ 実測する", self.meter_click,
                                        kind="mint", bg=th.CARD, font=F["small"],
                                        padx=14, pady=6, width=210)
        self.btn_meter.pack(side="left")
        self.btn_use = th.RoundButton(mt2, "③ この速さを使う（逆側も逆算）",
                                      self.meter_use, kind="primary", bg=th.CARD,
                                      font=F["small"], padx=12, pady=6)
        th.RoundButton(mt2, "やめる", self.meter_cancel, kind="ghost", bg=th.CARD,
                       font=F["small"], padx=10, pady=6).pack(side="left", padx=6)
        self.lbl_meter = tk.Label(cs_, text="", bg=th.CARD, fg=th.INK_SUB,
                                  font=F["small"], anchor="w", justify="left",
                                  wraplength=740)
        self.lbl_meter.pack(fill="x", pady=(2, 0))

        # ③ 結果（手で直すこともできる）
        sp = tk.Frame(cs_, bg=th.CARD)
        sp.pack(fill="x", pady=(8, 0))
        tk.Label(sp, text="③ 結果　昼(05:15-20:25)", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(side="left")
        self.v_day = tk.StringVar()
        th.soft_entry(sp, self.v_day, width=6).pack(side="left", padx=4, ipady=3)
        tk.Label(sp, text="分　夜(20:25-05:15)", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        self.v_night = tk.StringVar()
        th.soft_entry(sp, self.v_night, width=6).pack(side="left", padx=4, ipady=3)
        tk.Label(sp, text="分（実時間）", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")
        tk.Label(cs_, text="1分以上あけて2回目を合わせると、進む速さを自動で測り直します",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w",
                                                                  pady=(2, 0))

        self.fold_restart = Fold(c, "定期再起動（ズレの自動補正）", F["cute_b"])
        self.fold_restart.pack(fill="x", pady=(6, 0))
        cr_ = self.fold_restart.body
        tk.Label(cr_, text="サーバーが落ちている間はゲーム内時間も止まります。"
                         "再起動の時刻を入れておくと、その分を自動で差し引きます",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=740,
                 justify="left").pack(anchor="w")
        r5 = tk.Frame(cr_, bg=th.CARD)
        r5.pack(fill="x", pady=(4, 0))
        tk.Label(r5, text="毎日", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        self.v_restarts = tk.StringVar()
        th.soft_entry(r5, self.v_restarts, width=24).pack(side="left", padx=4,
                                                          ipady=3)
        tk.Label(r5, text="に、", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        self.v_rmin = tk.StringVar()
        th.soft_entry(r5, self.v_rmin, width=5).pack(side="left", padx=4, ipady=3)
        tk.Label(r5, text="分ほど止まる", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        tk.Label(cr_, text="例: 6:00, 12:00, 18:00 のようにカンマ区切りで",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w")
        self.lbl_restart = tk.Label(cr_, text="", bg=th.CARD, fg=th.INK_SUB,
                                    font=F["small"], anchor="w")
        self.lbl_restart.pack(fill="x")

        self.fold_watch = Fold(c, "サーバーを見張る（ズレの自動補正）", F["cute_b"])
        self.fold_watch.pack(fill="x", pady=(6, 0))
        cw_ = self.fold_watch.body
        iv = tk.Frame(cw_, bg=th.CARD)
        iv.pack(fill="x", pady=(0, 4))
        tk.Label(iv, text="見に行く間隔", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        self.v_ival = tk.StringVar(value="%g" % self.app.cfg.get("watch_interval",
                                                                 60))
        e2 = th.soft_entry(iv, self.v_ival, width=5)
        e2.pack(side="left", padx=4, ipady=3)
        e2.bind("<Return>", lambda ev: self.save_interval())
        tk.Label(iv, text="秒ごと", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        th.RoundButton(iv, "決定", self.save_interval, kind="soft", bg=th.CARD,
                       font=F["small"], padx=12, pady=5).pack(side="left", padx=8)
        self.lbl_ival = tk.Label(iv, text="", bg=th.CARD, fg=th.INK_SUB,
                                 font=F["small"])
        self.lbl_ival.pack(side="left")
        tk.Label(cw_, text="短くすると日の変わり目をつかまえる精度が上がりますが、"
                          "Epicへの問い合わせが増えます（20秒以上・既定60秒）",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=740,
                 justify="left").pack(anchor="w", pady=(0, 4))
        tk.Label(cw_, text="IPを入れて「🔍 マップを探す」を押すと、そのサーバーの"
                         "マップ一覧が出ます。選ぶと死活を見張って、落ちている間は"
                         "時計を止めます。ARKの日付が変わるたびに速さも自動で測り直します",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=740,
                 justify="left").pack(anchor="w")
        r4 = tk.Frame(cw_, bg=th.CARD)
        r4.pack(fill="x", pady=(4, 0))
        self.v_addr = tk.StringVar()
        th.soft_entry(r4, self.v_addr, width=26).pack(side="left", ipady=3)
        tk.Label(r4, text=" 例 1.2.3.4:7980（ゲームポート）", bg=th.CARD,
                 fg=th.INK_SUB, font=F["small"]).pack(side="left", padx=4)
        th.RoundButton(r4, "▶ ためす", self.test_addr, kind="soft", bg=th.CARD,
                       font=F["small"], padx=12, pady=5).pack(side="left", padx=6)
        th.RoundButton(r4, "🔍 マップを探す", self.find_servers, kind="accent",
                       bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left")
        th.RoundButton(r4, "↺ 学習をやり直す", self.forget_learned, kind="ghost",
                       bg=th.CARD, font=F["small"], padx=10,
                       pady=5).pack(side="left", padx=6)
        self.pick_box = tk.Frame(cw_, bg=th.CARD)
        self.pick_box.pack(fill="x", pady=(4, 0))
        self.lbl_watch = tk.Label(cw_, text="", bg=th.CARD, fg=th.INK_SUB,
                                  font=F["small"], anchor="w", justify="left",
                                  wraplength=740)
        self.lbl_watch.pack(fill="x", pady=(4, 0))

        for v in (self.v_day, self.v_night, self.v_addr,
                  self.v_restarts, self.v_rmin):
            v.trace_add("write", lambda *a: self.save_fields())
        self.rebuild()


    # ---------------- タップで速さを実測する ----------------
    def meter_click(self):
        """1回目で開始、2回目以降は「いま押した」として記録する。"""
        c = self.app.clocks.get()
        if c is None:
            self.lbl_meter.config(text="⚠ さきにマップを追加してください",
                                  fg=th.PINK_DK)
            return
        if self.meter is None:
            try:
                step = max(1, int(float(self.v_step.get() or 1)))
            except ValueError:
                step = 1
            want = self.v_phase.get()
            if want == "day":
                self.meter_phase = False
            elif want == "night":
                self.meter_phase = True
            elif c.synced:
                self.meter_phase = G.is_night(c.game_at())
            else:
                # まだ合わせていないと昼夜が分からない。勝手に昼にしない。
                self.lbl_meter.config(
                    text="⚠ まだ時刻を合わせていないので、昼か夜かを選んでから"
                         "押してください", fg=th.PINK_DK)
                return
            self.meter = G.TapMeter(step)
            self.btn_meter.set_text("ここで押す（0回）")
            self.lbl_meter.config(
                text="いま測っているのは【%s】です。ゲーム内の時計を見ながら、"
                     "%d分ごとに押してください。3回以上で結果が出ます"
                     % ("夜" if self.meter_phase else "昼", step), fg=th.INK)
            return
        n = self.meter.tap()
        self.btn_meter.set_text("ここで押す（%d回）" % n)
        self._meter_report()

    def _meter_report(self):
        m = self.meter
        per = m.per_game_minute()
        if per is None:
            self.lbl_meter.config(text="あと %d回 押すと結果が出ます" % (2 - len(m.taps)),
                                  fg=th.INK)
            return
        half = m.phase_real(bool(self.meter_phase)) / 60.0
        sp = m.spread()
        phase = "夜" if self.meter_phase else "昼"
        msg = ("ゲーム内1分 = %.1f秒 ／ %sぜんぶで %.1f分" % (per, phase, half))
        if sp is not None:
            msg += "（ばらつき %.1f秒）" % sp
        if m.count >= 3:
            msg += "　→ 「この速さを使う」で反映できます"
            self.btn_use.pack(side="left", padx=6)
        self.lbl_meter.config(text=msg, fg=th.MINT if m.count >= 3 else th.INK)

    def meter_use(self):
        """測ったほうを入れて、逆側は1日の長さの残りから逆算する。"""
        c = self.app.clocks.get()
        m = self.meter
        if c is None or m is None or m.phase_real() is None:
            return
        night = bool(self.meter_phase)
        ok, msg = c.apply_measured_phase(m.phase_real(night), night)
        if not ok:
            self.lbl_meter.config(text="⚠ " + msg, fg=th.PINK_DK)
            return
        self.app.save_clocks()
        self.meter_cancel()
        self._load_fields()
        self.update_view()          # 速さが変わったので残り時間を出し直す
        self.lbl_meter.config(text=msg,
                              fg=th.MINT if msg.startswith("✅") else th.PINK_DK)

    def meter_cancel(self):
        self.meter = None
        self.meter_phase = None
        self.btn_meter.set_text("⏱ 実測する")
        self.btn_use.pack_forget()
        self.lbl_meter.config(text="", fg=th.INK_SUB)

    # ---------------- マップ一覧 ----------------
    def rebuild(self):
        for w in self.rows_box.winfo_children():
            w.destroy()
        self.rows.clear()
        cs = self.app.clocks
        if not cs.order:
            tk.Label(self.rows_box, text="下の欄でサーバーを探して追加してください",
                     bg=th.CARD, fg=th.INK_SUB, font=self.app.F["small"]).pack(
                anchor="w", pady=6)
        for name in cs.order:
            self.rows[name] = self._row(name)
        self._load_fields()
        self.update_view()

    def _row(self, name):
        F = self.app.F
        row = tk.Frame(self.rows_box, bg=th.CARD)
        row.pack(fill="x", pady=1)
        pick = th.RoundButton(row, G.map_label(name),
                              lambda n=name: self.select(n),
                              kind="soft", bg=th.CARD, font=F["small"],
                              padx=12, pady=5)
        pick.pack(side="left")
        th.RoundButton(row, "✕", lambda n=name: self.del_map(n), kind="danger",
                       bg=th.CARD, font=F["small"], padx=9,
                       pady=5).pack(side="right", padx=2)
        lbl = tk.Label(row, text="", bg=th.CARD, fg=th.INK, font=F["ui"],
                       anchor="w")
        lbl.pack(side="left", padx=10)
        return {"btn": pick, "label": lbl}

    # ---------------- サーバーの様子 ----------------
    def poke_watch(self):
        """次の見回りを待たずに、いますぐ見に行かせる。"""
        if not self.app._watch_targets():
            self.lbl_poke.config(text="  ⚠ アドレスの入ったマップがありません",
                                 fg=th.PINK_DK)
            return
        self.app.watcher.poke()
        self._poke_at = time.time()
        self.lbl_poke.config(text="  見に行っています…", fg=th.INK_SUB)

    def _stat_row(self, name):
        F = self.app.F
        row = tk.Frame(self.stat_box, bg=th.CARD)
        row.pack(fill="x", pady=1)
        lamp = tk.Label(row, text="●", bg=th.CARD, fg=th.INK_SUB, font=F["ui"])
        lamp.pack(side="left", padx=(0, 4))
        bell = tk.Label(row, text="", bg=th.CARD, font=F["small"], cursor="hand2",
                        width=2)
        bell.pack(side="left")
        bell.bind("<Button-1>", lambda e, n=name: self.toggle_notify(n))
        nm = tk.Label(row, text=G.map_label(name), bg=th.CARD, fg=th.INK,
                      font=F["ui"], anchor="w", width=18)
        nm.pack(side="left")
        info = tk.Label(row, text="", bg=th.CARD, fg=th.INK_SUB, font=F["small"],
                        anchor="w")
        info.pack(side="left", fill="x", expand=True)
        return {"row": row, "lamp": lamp, "bell": bell, "info": info}

    def toggle_notify(self, name):
        """そのマップの「落ちた／戻った」の知らせを入切する。"""
        c = self.app.clocks.clocks.get(name)
        if c is None:
            return
        c.notify = not c.notify
        self.app.save_clocks()
        self.refresh_status()
        self.lbl_poke.config(
            text="  %s %s の知らせを%s" % ("🔔" if c.notify else "🔕",
                                           G.map_label(name),
                                           "出します" if c.notify else "止めました"),
            fg=th.MINT if c.notify else th.INK_SUB)

    def refresh_status(self, now=None):
        """見張っているマップぶんの行を出し直す。"""
        now = now if now is not None else time.time()
        targets = [n for n, _a in self.app._watch_targets()]
        if list(self.stat_rows) != targets:
            for r in self.stat_rows.values():
                r["row"].destroy()
            self.stat_rows = {n: self._stat_row(n) for n in targets}
        live = 0
        for name, r in self.stat_rows.items():
            c = self.app.clocks.clocks.get(name)
            on = bool(c is not None and c.notify)
            r["bell"].config(text="🔔" if on else "🔕",
                             fg=th.INK if on else th.LINE)
            st = self.app.watcher.state.get(name)
            if st is None:
                r["lamp"].config(fg=th.INK_SUB)
                r["info"].config(text="まだ見ていません")
                continue
            seen = st.get("at") or now
            ago = max(0, int(now - seen))
            when = "%d秒前" % ago if ago < 60 else "%d分前" % (ago // 60)
            if st.get("online"):
                live += 1
                r["lamp"].config(fg=th.MINT)
                r["info"].config(
                    text="%s/%s人　Day %s　%s"
                         % (st.get("players", "?"), st.get("max_players", "?"),
                            st.get("day", "?"), when),
                    fg=th.INK_SUB)
            else:
                r["lamp"].config(fg=th.RED)
                r["info"].config(text="%s　%s" % (st.get("why") or "落ちています",
                                                 when), fg=th.PINK_DK)
        if targets:
            head = "サーバーの様子 — %d/%d 起動中" % (live, len(targets))
        else:
            head = "サーバーの様子（見張っているマップがありません）"
        if self.fold_stat.title != head:
            self.fold_stat.set_title(head)
        # 見に行った結果が返ってきたら「見に行っています…」を消す。
        # 全部落ちていても返事は返るので、生きている数ではなく時刻で見る。
        if getattr(self, "_poke_at", 0):
            got = [self.app.watcher.state.get(n, {}).get("at") or 0
                   for n in targets]
            if got and min(got) >= self._poke_at:
                self._poke_at = 0
                self.lbl_poke.config(text="  ✅ 見てきました", fg=th.MINT)

    def _say_total(self, text, fg, secs=12):
        """①の脇に一言。しばらくしたら進み具合の表示に戻る。"""
        self.lbl_total.config(text=text, fg=fg)
        self._total_msg_until = time.time() + secs

    # ---------------- 1日の長さの自動計測 ----------------
    def measure_one(self):
        """いま選んでいるマップだけ測りはじめる。"""
        name = self.app.clocks.current
        c = self.app.clocks.get()
        if c is None:
            self._say_total("⚠ さきにマップを追加してください", th.PINK_DK)
            return
        ok, why = c.start_measure()
        self.app.save_clocks()
        self.update_view()
        self._say_total(("⏱ %s を%s" % (G.map_label(name), why)) if ok
                        else "⚠ " + why,
                        th.MINT if ok else th.PINK_DK)

    def toggle_bulk_measure(self):
        """どのマップを測るかの選び場を開け閉めする。"""
        self.bulk_open = not self.bulk_open
        if not self.bulk_open:
            self.bulk_box.pack_forget()
            self.bulk_vars = {}      # 閉じたら選択は残さない
            return
        for w in self.bulk_rows.winfo_children():
            w.destroy()
        self.bulk_vars = {}
        F = self.app.F
        cs = self.app.clocks
        ready = [n for n in cs.order
                 if (cs.clocks.get(n) is not None and cs.clocks[n].address)]
        if not ready:
            tk.Label(self.bulk_rows, text="アドレスの入ったマップがありません。"
                                          "IPからマップを登録してください",
                     bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w")
        row = None
        for i, n in enumerate(ready):
            if i % 3 == 0:
                row = tk.Frame(self.bulk_rows, bg=th.CARD)
                row.pack(fill="x")
            c = cs.clocks[n]
            # まだ測れていないマップを最初から選んでおく
            v = tk.BooleanVar(value=not c.total_measured)
            self.bulk_vars[n] = v
            mark = "" if not c.total_measured else "（測定済 %.0f分）" % (
                c.full_day_real() / 60)
            if c.measuring:
                mark = "（測定中）"
            tk.Checkbutton(row, text=G.map_label(n) + mark, variable=v, bg=th.CARD,
                           fg=th.INK, activebackground=th.CARD,
                           activeforeground=th.INK, selectcolor=th.FIELD,
                           font=F["small"], bd=0, highlightthickness=0,
                           anchor="w", width=26).pack(side="left")
        self.bulk_box.pack(fill="x", pady=(4, 0), before=self._bulk_anchor)

    def _bulk_all(self, on):
        for v in self.bulk_vars.values():
            v.set(bool(on))

    def measure_selected(self):
        """選んだマップをまとめて測りはじめる。"""
        picked = [n for n, v in self.bulk_vars.items() if v.get()]
        if not picked:
            self._say_total("⚠ 測るマップを選んでください", th.PINK_DK)
            return
        started, skipped = [], []
        for n in picked:
            c = self.app.clocks.clocks.get(n)
            if c is None:
                continue
            ok, _why = c.start_measure()
            (started if ok else skipped).append(n)
        self.app.save_clocks()
        self.toggle_bulk_measure()
        self.update_view()
        msg = "⏱ %d個のマップを測りはじめました（%s）" % (
            len(started), "、".join(G.map_label(n) for n in started[:6]))
        if len(started) > 6:
            msg += " ほか"
        if skipped:
            msg += "／%d個はアドレスが無いので飛ばしました" % len(skipped)
        self._say_total(msg, th.MINT if started else th.PINK_DK)

    def measure_text(self, name, c):
        """測定中の進み具合。測っていなければ None。"""
        if not c.measuring:
            return None
        at = self.app.watcher.day_at(name)
        if not at:
            return "最初の日の変わり目を待っています"
        left = c.full_day_real() - (time.time() - at)
        if left <= 0:
            return "まもなく結果が出ます"
        return "あと約%d分" % max(1, int(round(left / 60)))

    def apply_total(self):
        """1日の長さを入れ直す。昼と夜の比は保ったまま伸び縮みさせる。"""
        c = self.app.clocks.get()
        if c is None:
            self._say_total("⚠ さきにマップを追加してください", th.PINK_DK)
            return
        try:
            mins = float(self.v_total.get().strip())
        except ValueError:
            self._say_total("⚠ 数字を入れてください", th.PINK_DK)
            return
        if not 1 <= mins <= 24 * 60:
            self._say_total("⚠ 1〜1440分で入れてください", th.PINK_DK)
            return
        c.set_total(mins * 60)
        c.total_measured = True
        self.app.save_clocks()
        self._load_fields()
        self.update_view()
        self._say_total("✅ 1日を %.1f分にしました。②へどうぞ" % mins, th.MINT)

    def save_interval(self):
        """見張りの間隔を変える。見張りスレッドは次の周回から新しい値で動く。"""
        try:
            sec = float(self.v_ival.get().strip())
        except ValueError:
            self.lbl_ival.config(text="  ⚠ 数字を入れてください", fg=th.PINK_DK)
            return
        if sec < 20:
            self.lbl_ival.config(text="  ⚠ 20秒以上にしてください", fg=th.PINK_DK)
            return
        self.app.cfg["watch_interval"] = sec
        self.app.watcher.interval = sec
        self.app.save_cfg()
        self.lbl_ival.config(text="  ✅ %g秒ごとにしました" % sec, fg=th.MINT)

    def toggle_maps(self, show=None):
        self.maps_open = (not self.maps_open) if show is None else bool(show)
        if self.maps_open:
            self.maps_box.pack(fill="x", pady=(8, 0))
        else:
            self.maps_box.pack_forget()
        self.btn_maps.set_text("🗺 %s %s"
                               % (G.map_label(self.app.clocks.current) or "マップ",
                                  "▴" if self.maps_open else "▾"))

    def select(self, name):
        self.app.clocks.current = name
        self.app.save_clocks()
        self._load_fields()
        self.lbl_msg.config(text="")
        self.toggle_maps(False)      # 選んだら閉じる
        self.update_view()

    def add_map(self):
        name = self.v_new.get().strip()
        if not name:
            self.lbl_msg.config(text="⚠ マップの名前を入れてください", fg=th.PINK_DK)
            return
        if not self.app.clocks.add(name):
            self.lbl_msg.config(text="⚠ その名前はもうあります", fg=th.PINK_DK)
            return
        self.v_new.set("")
        self.app.save_clocks()
        self.rebuild()
        self.toggle_maps(True)

    def search_servers(self):
        """名前かIPでサーバーを探して、結果を並べる。

        名前検索は**いま起動しているサーバーしか出ない**（落ちていると
        Epicへの登録が消えるため）。落ちているマップも登録したいときは
        IPで探すか、起動しているうちに追加しておく。
        """
        text = self.v_bulk.get().strip()
        if not text:
            self.lbl_bulk.config(text="  ⚠ 名前かIPを入れてください",
                                 fg=th.PINK_DK)
            return
        self.lbl_bulk.config(text="  探しています…", fg=th.INK_SUB)
        self.update_idletasks()
        self.found = sorted(self.app.watcher.search(text),
                            key=lambda x: (x.get("name") or "",
                                           x.get("port") or 0))
        self.show_found()
        if not self.found:
            self.lbl_bulk.config(text="  ⚠ 見つかりません"
                                      "（落ちているサーバーは出ません）",
                                 fg=th.PINK_DK)
        else:
            self.lbl_bulk.config(text="  %d件みつかりました" % len(self.found),
                                 fg=th.MINT)

    def show_found(self):
        F = self.app.F
        for w in self.found_box.winfo_children():
            w.destroy()
        if not self.found:
            return
        head = tk.Frame(self.found_box, bg=th.CARD)
        head.pack(fill="x", pady=(4, 2))
        th.RoundButton(head, "＋ ぜんぶ追加", lambda: self.add_found(None),
                       kind="primary", bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left")
        tk.Label(head, text="  追加したマップは、その場から見張りはじめます",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(side="left")
        for i, srv in enumerate(self.found[:40]):
            row = tk.Frame(self.found_box, bg=th.CARD)
            row.pack(fill="x", pady=1)
            th.RoundButton(row, "＋", lambda k=i: self.add_found(k), kind="soft",
                           bg=th.CARD, font=F["small"], padx=10,
                           pady=4).pack(side="left")
            tk.Label(row, text=G.map_label(srv.get("map")), bg=th.CARD,
                     fg=th.INK, font=F["ui"], anchor="w",
                     width=16).pack(side="left", padx=6)
            tk.Label(row, text="%s／%s人／%s:%s"
                              % ((srv.get("name") or "")[:34],
                                 srv.get("players", "?"), srv.get("ip", "?"),
                                 srv.get("port", "?")),
                     bg=th.CARD, fg=th.INK_SUB, font=F["small"],
                     anchor="w").pack(side="left", fill="x", expand=True)

    def _unique_name(self, base):
        """同じマップ名がもうあるときは、後ろに数字を足して分ける。"""
        base = base or "?"
        if base not in self.app.clocks.clocks:
            return base
        for k in range(2, 30):
            cand = "%s %d" % (base, k)
            if cand not in self.app.clocks.clocks:
                return cand
        return None

    def add_found(self, index):
        """検索結果を一覧に追加する。index が None なら全部。"""
        picks = self.found if index is None else [self.found[index]]
        added, skipped = [], 0
        for srv in picks:
            addr = "%s:%s" % (srv.get("ip"), srv.get("port"))
            if any(c.address == addr for c in self.app.clocks.clocks.values()):
                skipped += 1              # そのサーバーはもう登録済み
                continue
            name = self._unique_name((srv.get("map") or "").replace("_WP", ""))
            if not name or not self.app.clocks.add(name):
                skipped += 1
                continue
            c = self.app.clocks.get(name)
            if c is not None:
                c.address = addr
            added.append(name)
        self.app.save_clocks()
        self.rebuild()
        self.toggle_maps(True)
        msg = "  ✅ %d個を追加しました" % len(added)
        if skipped:
            msg += "（%d個は登録済み）" % skipped
        self.lbl_bulk.config(text=msg, fg=th.MINT if added else th.INK_SUB)

    def del_map(self, name):
        if not self.app.ask_delete(name, parent=self.winfo_toplevel()):
            return
        self.app.clocks.remove(name)
        self.app.save_clocks()
        self.rebuild()

    # ---------------- 選択中マップの入出力 ----------------
    def _load_fields(self):
        c = self.app.clocks.get()
        self._loading = True
        try:
            if c is None:
                self.v_total.set("")
                self.v_day.set("")
                self.v_night.set("")
                self.v_addr.set("")
                self.v_restarts.set("")
                self.v_rmin.set("")
            else:
                self.v_total.set("%g" % round(c.full_day_real() / 60, 1))
                self.v_day.set("%g" % round(c.day_real / 60, 1))
                self.v_night.set("%g" % round(c.night_real / 60, 1))
                self.v_addr.set(c.address or "")
                self.v_restarts.set(", ".join(c.restarts))
                self.v_rmin.set("%g" % round(c.restart_minutes, 1))
        finally:
            self._loading = False

    def save_fields(self):
        if self._loading:
            return
        c = self.app.clocks.get()
        if c is None:
            return
        try:
            d = float(self.v_day.get() or 0)
            n = float(self.v_night.get() or 0)
        except ValueError:
            d = n = 0
        if d > 0:
            c.day_real = d * 60
        if n > 0:
            c.night_real = n * 60
        c.address = self.v_addr.get().strip()
        times = []
        for part in self.v_restarts.get().replace("、", ",").split(","):
            part = part.strip()
            if part and G.parse_game_time(part) is not None:
                times.append(part)
        c.restarts = times
        try:
            c.restart_minutes = max(0.0, float(self.v_rmin.get() or 0))
        except ValueError:
            pass
        self.app.save_clocks()
        self.update_view()

    def do_sync(self):
        c = self.app.clocks.get()
        if c is None:
            self.lbl_msg.config(text="⚠ さきにマップを追加してください", fg=th.PINK_DK)
            return
        g = G.parse_game_time(self.v_time.get())
        if g is None:
            self.lbl_msg.config(text="⚠ 17:30 のように入れてください", fg=th.PINK_DK)
            return
        # ズレを見てから合わせる。入れ直すたびに速さが正しくなっていく
        ok, why = c.resync(g)
        self.lbl_msg.config(text=why, fg=th.MINT if ok else th.INK_SUB)
        if ok:
            self._load_fields()
        self.app.save_clocks()
        self.v_time.set("")
        self.update_view()

    def make_timer(self, which):
        c = self.app.clocks.get()
        if c is None or not c.synced:
            self.lbl_msg.config(text="⚠ さきに時刻を合わせてください", fg=th.PINK_DK)
            return
        left = c.next_night() if which == "night" else c.next_day()
        if not left or left <= 0:
            return
        name = self.app.clocks.current
        label = "%s %s" % ("🌙 夜になる" if which == "night" else "☀ 朝になる", name)
        note = "ゲーム内 %s になったら" % G.fmt_game_time(
            G.NIGHT_START if which == "night" else G.DAY_START)
        self.app.add_game_time_timer(label, left, note)
        self.lbl_msg.config(text="⏰ タイマーを作りました（%s後）" % _hms(left),
                            fg=th.MINT)

    def make_at_timer(self):
        """好きなゲーム内時刻になったら知らせるタイマーを作る。"""
        c = self.app.clocks.get()
        if c is None or not c.synced:
            self.lbl_msg.config(text="⚠ さきに時刻を合わせてください", fg=th.PINK_DK)
            return
        target = G.parse_game_time(self.v_at.get())
        if target is None:
            self.lbl_msg.config(text="⚠ 20:00 のように入れてください", fg=th.PINK_DK)
            return
        left = c.real_until(target)
        if not left or left <= 0:
            self.lbl_msg.config(text="⚠ その時刻は計算できませんでした", fg=th.PINK_DK)
            return
        name = self.app.clocks.current
        self.app.add_game_time_timer(
            "🕐 %s %s" % (name, G.fmt_game_time(target)), left,
            "ゲーム内 %s になったら" % G.fmt_game_time(target))
        self.lbl_msg.config(text="⏰ タイマーを作りました（%s後）" % _hms(left),
                            fg=th.MINT)

    def test_addr(self):
        addr = self.v_addr.get().strip()
        if not addr:
            self.lbl_watch.config(text="⚠ アドレスを入れてください", fg=th.PINK_DK)
            return
        self.lbl_watch.config(text="問い合わせ中…", fg=th.INK_SUB)
        self.update_idletasks()
        r = self.app.watcher.check_now(self.app.clocks.current, addr)
        if r.get("online"):
            self.lbl_watch.config(
                text="✅ 起きています — %s ／ %s ／ %s/%s人 ／ Day %s"
                     % (r.get("name", "?")[:38], r.get("map", "?"),
                        r.get("players", "?"), r.get("max_players", "?"),
                        r.get("day", "?")), fg=th.MINT)
        else:
            self.lbl_watch.config(text="⚠ %s" % r.get("why", "つながりません"),
                                  fg=th.PINK_DK)

    def forget_learned(self):
        """測り直しからやり直す（変な値を掴んだときの逃げ道）。"""
        c = self.app.clocks.get()
        if c is None:
            return
        c.forget_learned()
        self.app.watch_msg.pop(self.app.clocks.current, None)
        self.app.save_clocks()
        self._load_fields()
        self.lbl_watch.config(text="↺ 覚えた速さと変わり目を捨てました。"
                                   "Dayが2回変わると測り直します", fg=th.INK_SUB)
        self.update_view()

    def find_servers(self):
        """IPからマップ一覧を引いて、押すとそのポートを入れる。"""
        addr = self.v_addr.get().strip()
        if not addr:
            self.lbl_watch.config(text="⚠ さきにIPを入れてください", fg=th.PINK_DK)
            return
        self.lbl_watch.config(text="探しています…", fg=th.INK_SUB)
        self.update_idletasks()
        found = self.app.watcher.list_servers(addr)
        for w in self.pick_box.winfo_children():
            w.destroy()
        if not found:
            self.lbl_watch.config(text="⚠ そのIPにサーバーが見つかりません",
                                  fg=th.PINK_DK)
            return
        ip = addr.replace(":", " ").split()[0]
        self.lbl_watch.config(text="✅ %d個 見つかりました。使うマップを押してください"
                                   % len(found), fg=th.MINT)
        for srv in sorted(found, key=lambda x: x.get("port") or 0):
            label = "%s  %s/%s人" % (srv["map"].replace("_WP", ""),
                                     srv["players"], srv["max_players"])
            th.Chip(self.pick_box, label,
                    lambda s=srv, i=ip: self.pick_server(i, s),
                    bg=th.CARD, font=self.app.F["small"]).pack(side="left",
                                                               padx=2, pady=2)

    def pick_server(self, ip, srv):
        self.v_addr.set("%s:%s" % (ip, srv["port"]))
        self.save_fields()
        self.lbl_watch.config(text="✅ %s を見張ります（%s）"
                                   % (G.map_label(srv["map"]),
                                      srv["name"][:36]), fg=th.MINT)
        for w in self.pick_box.winfo_children():
            w.destroy()

    # ---------------- 表示 ----------------
    def update_view(self, now=None):
        self.refresh_status(now)
        cs = self.app.clocks
        for name, row in self.rows.items():
            c = cs.clocks.get(name)
            if c is None:
                continue
            on = name == cs.current
            row["btn"].fill = th.PINK if on else th.BG_SOFT
            row["btn"].itemconfigure(row["btn"].shape, fill=row["btn"].fill)
            row["btn"].itemconfigure(row["btn"].label,
                                     fill=th.ON_ACCENT if on else th.INK)
            if not c.synced:
                row["label"].config(text="まだ合わせていません", fg=th.INK_SUB)
                continue
            g = c.game_at(now)
            night = G.is_night(g)
            if c.paused:
                row["label"].config(
                    text="⏸ %s ／ 止まっています（サーバーが落ちています）"
                         % G.fmt_game_time(g), fg=th.PINK_DK)
                continue
            left = c.next_day(now) if night else c.next_night(now)
            mark = ""
            st = self.app.watcher.state.get(name)
            if st is not None:
                mark = "  ✅" if st.get("online") else "  ⚠ 落ちています"
            prog = self.measure_text(name, c)
            if prog:
                mark += "  ⏱" + prog
            row["label"].config(
                text="%s %s ／ %s まで %s%s" % (
                    "🌙" if night else "☀", G.fmt_game_time(g),
                    "朝" if night else "夜", _hms(left), mark),
                fg=th.LAV if night else th.INK)

        cur = self.rows.get(cs.current)
        self.lbl_now.config(text=cur["label"].cget("text") if cur else "",
                            fg=cur["label"].cget("fg") if cur else th.INK_SUB)
        self.btn_maps.set_text("🗺 %s %s" % (G.map_label(cs.current) or "マップ",
                                             "▴" if self.maps_open else "▾"))

        c = cs.get()
        if c is None:
            self.lbl_sel.config(text="マップが登録されていません")
            self.lbl_total.config(text="")
            return
        self.lbl_sel.config(text="⚙ %s の設定" % G.map_label(cs.current))
        if c.restarts and c.restart_minutes > 0:
            self.lbl_restart.config(
                text="→ %s に %g分ずつ、自動で差し引きます"
                     % ("・".join(c.restarts), c.restart_minutes), fg=th.MINT)
        else:
            self.lbl_restart.config(text="（未設定）", fg=th.INK_SUB)
        if time.time() >= self._total_msg_until:
            prog = self.measure_text(cs.current, c)
            if prog:
                txt, col = "⏱ 測定中 — " + prog, th.MINT
            elif c.total_measured:
                txt, col = ("✅ 1日 %.1f分 ／ 昼 %.1f分・夜 %.1f分（%s）"
                            % (c.full_day_real() / 60, c.day_real / 60,
                               c.night_real / 60, c.fit_note())), th.MINT
            else:
                txt, col = ("⏳ まだ測れていません。「⏱ 自動で測る」を押すと、"
                            "日の変わり目を2回つかまえて勝手に測ります"), th.INK_SUB
            self.lbl_total.config(text=txt, fg=col)
        st = self.app.watcher.state.get(cs.current)
        msg = self.app.watch_msg.get(cs.current)
        head = self.lbl_watch.cget("text")
        if st is not None and not head.startswith(("⚠", "問", "探", "✅ %d" % 0)):
            if st.get("online"):
                txt = "✅ 見張り中 — %s/%s人 ／ Day %s" % (
                    st.get("players", "?"), st.get("max_players", "?"),
                    st.get("day", "?"))
                if msg:
                    txt += " ／ " + msg
                self.lbl_watch.config(text=txt, fg=th.MINT)
            else:
                self.lbl_watch.config(text="⚠ いま落ちています（時計を止めています）",
                                      fg=th.PINK_DK)
