# -*- coding: utf-8 -*-
"""🌙 ゲーム内時計のページ（マップごと）。

ARK は「今の時刻を返す」RCONコマンドを持っていないので、他人のサーバーから
時刻を取ることはできない。そこで、ゲーム内のHUD（Hキー）で読んだ時刻を
1回入れてもらい、あとは実時間から計算して進める。

ズレる原因は主に「サーバーが落ちていた時間」。ゲーム内時間はサーバーが動いて
いる間しか進まないので、A2S で死活を見張って、落ちている間は時計を止める。
"""
from __future__ import annotations

import tkinter as tk

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


class GameTimePage(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=th.BG)
        self.app = app
        self._loading = False
        self.meter = None
        self.meter_phase = None
        F = app.F

        # ---- 上: マップの一覧 ----
        top = th.Card(self, bg=th.BG)
        top.pack(fill="x")
        b = top.body
        head = tk.Frame(b, bg=th.CARD)
        head.pack(fill="x")
        tk.Label(head, text="マップ", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(side="left")
        th.RoundButton(head, "＋ 追加", self.add_map, kind="soft", bg=th.CARD,
                       font=F["small"], padx=12, pady=5).pack(side="right")
        self.v_new = tk.StringVar()
        ent = th.soft_entry(head, self.v_new, width=16)
        ent.pack(side="right", padx=6, ipady=3)
        ent.bind("<Return>", lambda e: self.add_map())

        self.rows_box = tk.Frame(b, bg=th.CARD)
        self.rows_box.pack(fill="x", pady=(8, 0))
        self.rows = {}

        # ---- 下: 選んだマップの設定 ----
        conf = th.Card(self, bg=th.BG)
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

        sp = tk.Frame(c, bg=th.CARD)
        sp.pack(fill="x", pady=(10, 0))
        tk.Label(sp, text="昼(05:30-17:30)", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        self.v_day = tk.StringVar()
        th.soft_entry(sp, self.v_day, width=6).pack(side="left", padx=4, ipady=3)
        tk.Label(sp, text="分　夜(17:30-05:30)", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        self.v_night = tk.StringVar()
        th.soft_entry(sp, self.v_night, width=6).pack(side="left", padx=4, ipady=3)
        tk.Label(sp, text="分（実時間）", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")
        self.lbl_total = tk.Label(sp, text="", bg=th.CARD, fg=th.INK_SUB,
                                  font=F["small"])
        self.lbl_total.pack(side="left", padx=10)
        tk.Label(c, text="1分以上あけて2回目を合わせると、進む速さを自動で測り直します",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w",
                                                                  pady=(2, 0))

        # ---- タップで実測 ----
        mt = tk.Frame(c, bg=th.CARD)
        mt.pack(fill="x", pady=(6, 0))
        self.btn_meter = th.RoundButton(mt, "⏱ 実測する", self.meter_click,
                                        kind="mint", bg=th.CARD, font=F["small"],
                                        padx=14, pady=6, width=210)
        self.btn_meter.pack(side="left")
        self.btn_use = th.RoundButton(mt, "この速さを使う", self.meter_use,
                                      kind="primary", bg=th.CARD, font=F["small"],
                                      padx=12, pady=6)
        th.RoundButton(mt, "やめる", self.meter_cancel, kind="ghost", bg=th.CARD,
                       font=F["small"], padx=10, pady=6).pack(side="left", padx=6)
        tk.Label(mt, text="何ゲーム内分ごとに押す", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left", padx=(8, 2))
        self.v_step = tk.StringVar(value="1")
        th.soft_entry(mt, self.v_step, width=4).pack(side="left", ipady=2)
        self.v_phase = tk.StringVar(value="auto")
        for txt, val in (("自動", "auto"), ("昼", "day"), ("夜", "night")):
            tk.Radiobutton(mt, text=txt, variable=self.v_phase, value=val,
                           bg=th.CARD, fg=th.INK, activebackground=th.CARD,
                           activeforeground=th.INK, selectcolor=th.FIELD,
                           font=F["small"], bd=0,
                           highlightthickness=0).pack(side="left", padx=(6, 0))
        self.lbl_meter = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
                                  font=F["small"], anchor="w", justify="left",
                                  wraplength=740)
        self.lbl_meter.pack(fill="x", pady=(2, 0))

        tk.Label(c, text="定期再起動（ズレの自動補正）", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        tk.Label(c, text="サーバーが落ちている間はゲーム内時間も止まります。"
                         "再起動の時刻を入れておくと、その分を自動で差し引きます",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=740,
                 justify="left").pack(anchor="w")
        r5 = tk.Frame(c, bg=th.CARD)
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
        tk.Label(c, text="例: 6:00, 12:00, 18:00 のようにカンマ区切りで",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w")
        self.lbl_restart = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
                                    font=F["small"], anchor="w")
        self.lbl_restart.pack(fill="x")

        tk.Label(c, text="\nサーバーを見張る（ズレの自動補正）", bg=th.CARD,
                 fg=th.INK, font=F["cute_b"]).pack(anchor="w")
        tk.Label(c, text="IPを入れて「🔍 マップを探す」を押すと、そのサーバーの"
                         "マップ一覧が出ます。選ぶと死活を見張って、落ちている間は"
                         "時計を止めます。ARKの日付が変わるたびに速さも自動で測り直します",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=740,
                 justify="left").pack(anchor="w")
        r4 = tk.Frame(c, bg=th.CARD)
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
        self.pick_box = tk.Frame(c, bg=th.CARD)
        self.pick_box.pack(fill="x", pady=(4, 0))
        self.lbl_watch = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
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
        half = m.half_day_real() / 60.0
        sp = m.spread()
        phase = "夜" if self.meter_phase else "昼"
        msg = ("ゲーム内1分 = %.1f秒 ／ %s12時間ぶん = %.1f分" % (per, phase, half))
        if sp is not None:
            msg += "（ばらつき %.1f秒）" % sp
        if m.count >= 3:
            msg += "　→ 「この速さを使う」で反映できます"
            self.btn_use.pack(side="left", padx=6)
        self.lbl_meter.config(text=msg, fg=th.MINT if m.count >= 3 else th.INK)

    def meter_use(self):
        c = self.app.clocks.get()
        m = self.meter
        if c is None or m is None or m.half_day_real() is None:
            return
        half_min = m.half_day_real() / 60.0
        self._loading = True
        try:
            if self.meter_phase:
                self.v_night.set("%g" % round(half_min, 1))
            else:
                self.v_day.set("%g" % round(half_min, 1))
        finally:
            self._loading = False
        self.save_fields()
        which = "夜" if self.meter_phase else "昼"
        self.meter_cancel()
        self.lbl_meter.config(text="✅ %sの長さを %.1f分にしました" % (which, half_min),
                              fg=th.MINT)

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
            tk.Label(self.rows_box, text="「＋ 追加」でマップを登録してください",
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
        pick = th.RoundButton(row, name, lambda n=name: self.select(n),
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

    def select(self, name):
        self.app.clocks.current = name
        self.app.save_clocks()
        self._load_fields()
        self.lbl_msg.config(text="")
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
                self.v_day.set("")
                self.v_night.set("")
                self.v_addr.set("")
                self.v_restarts.set("")
                self.v_rmin.set("")
            else:
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
        ok, why = c.calibrate(g)
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
                                   % (srv["map"], srv["name"][:36]), fg=th.MINT)
        for w in self.pick_box.winfo_children():
            w.destroy()

    # ---------------- 表示 ----------------
    def update_view(self, now=None):
        cs = self.app.clocks
        for name, row in self.rows.items():
            c = cs.clocks.get(name)
            if c is None:
                continue
            on = name == cs.current
            row["btn"].fill = th.PINK if on else th.BG_SOFT
            row["btn"].itemconfigure(row["btn"].shape, fill=row["btn"].fill)
            row["btn"].itemconfigure(row["btn"].label,
                                     fill="#FFFFFF" if on else th.INK)
            if not c.synced:
                row["label"].config(text="まだ合わせていません", fg=th.INK_SUB)
                continue
            g = c.game_at(now)
            night = G.is_night(g)
            left = c.next_day(now) if night else c.next_night(now)
            mark = ""
            st = self.app.watcher.state.get(name)
            if st is not None:
                mark = "  ✅" if st.get("online") else "  ⚠ 落ちています"
            row["label"].config(
                text="%s %s ／ %s まで %s%s" % (
                    "🌙" if night else "☀", G.fmt_game_time(g),
                    "朝" if night else "夜", _hms(left), mark),
                fg=th.LAV if night else th.INK)

        c = cs.get()
        if c is None:
            self.lbl_sel.config(text="マップが登録されていません")
            self.lbl_total.config(text="")
            return
        self.lbl_sel.config(text="⚙ %s の設定" % cs.current)
        if c.restarts and c.restart_minutes > 0:
            self.lbl_restart.config(
                text="→ %s に %g分ずつ、自動で差し引きます"
                     % ("・".join(c.restarts), c.restart_minutes), fg=th.MINT)
        else:
            self.lbl_restart.config(text="（未設定）", fg=th.INK_SUB)
        self.lbl_total.config(text="1日 %.1f分" % (c.full_day_real() / 60))
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
