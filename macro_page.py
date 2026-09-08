# -*- coding: utf-8 -*-
"""🖱 マクロのページ。連射の設定と入切。実際の送信は macro.py。"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

import afk
import macro
import theme as th


class MacroPage(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=th.BG)
        self.app = app
        self._capturing = False
        self.F = app.F
        F = app.F
        cfg = app.cfg

        # たまごマクロを足して縦に長くなったので、ページごとスクロールできる
        # ようにする（下のカードが画面の外へ出て押せなくなっていた）。
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
        self.bind_all("<MouseWheel>", self._wheel, add="+")

        # ---- 上: スイッチと状態 ----
        top = th.Card(self.inner, bg=th.BG)
        top.pack(fill="x")
        b = top.body
        row = tk.Frame(b, bg=th.CARD)
        row.pack(fill="x")
        self.btn = th.RoundButton(row, "▶ かまえる",
                                  lambda: self.toggle("hold"), kind="primary",
                                  bg=th.CARD, font=F["cute_b"], padx=20)
        self.btn.pack(side="left")
        self.btn_always = th.RoundButton(row, "▶ ずっと連射",
                                         lambda: self.toggle("always"),
                                         kind="accent", bg=th.CARD,
                                         font=F["cute_b"], padx=20)
        self.btn_always.pack(side="left", padx=8)
        self.btn_press = th.RoundButton(row, "⬇ 長押し", self.toggle_hold,
                                        kind="soft", bg=th.CARD,
                                        font=F["cute_b"], padx=20)
        self.btn_press.pack(side="left")
        self.lbl_state = tk.Label(row, text="", bg=th.CARD, fg=th.INK,
                                  font=F["cute"], anchor="w")
        self.lbl_state.pack(side="left", padx=14)
        self.lbl_sub = tk.Label(b, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="w", justify="left")
        self.lbl_sub.pack(fill="x", pady=(8, 0))

        # ---- 下: 設定 ----
        conf = th.Card(self.inner, bg=th.BG)
        conf.pack(fill="x", pady=(8, 0))
        c = conf.body

        tk.Label(c, text="連打の出しかた（どちらもいつでも使えます）",
                 bg=th.CARD, fg=th.INK, font=F["cute_b"]).pack(anchor="w")
        self.lbl_mode = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
                                 font=F["small"], wraplength=760,
                                 justify="left")
        self.lbl_mode.pack(anchor="w", pady=(2, 4))
        drow = tk.Frame(c, bg=th.CARD)
        drow.pack(fill="x", pady=(0, 10))
        tk.Label(drow, text="長押しと見なすまで", bg=th.CARD, fg=th.INK,
                 font=F["cute"], width=14, anchor="w").pack(side="left")
        self.v_delay = tk.StringVar(
            value="%g" % (float(cfg.get("macro_hold_delay_ms", 300)) / 1000.0))
        th.soft_entry(drow, self.v_delay, width=7).pack(side="left", ipady=3)
        tk.Label(drow, text=" 秒（これより短く押したら、ただのクリック）",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(side="left")
        self.v_blip = tk.BooleanVar(value=bool(cfg.get("blip", True)))
        tk.Checkbutton(c, text="入切したとき、画面の上に一瞬だけ出す",
                       variable=self.v_blip, command=self.save_blip,
                       bg=th.CARD, fg=th.INK, activebackground=th.CARD,
                       activeforeground=th.INK, selectcolor=th.FIELD,
                       font=F["cute"], bd=0, highlightthickness=0,
                       anchor="w").pack(anchor="w", pady=(4, 0))
        self.v_badge = tk.BooleanVar(value=bool(cfg.get("macro_badge", True)))
        tk.Checkbutton(c, text="連射が入っているあいだ、画面の左上に出しっぱなしにする",
                       variable=self.v_badge, command=self.save_badge,
                       bg=th.CARD, fg=th.INK, activebackground=th.CARD,
                       activeforeground=th.INK, selectcolor=th.FIELD,
                       font=F["cute"], bd=0, highlightthickness=0,
                       anchor="w").pack(anchor="w")
        tk.Label(c, text="切っているあいだは何も出ません。札はクリックを吸わないので、"
                         "ゲームの邪魔にはなりません",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=760,
                 justify="left").pack(anchor="w", pady=(0, 10))

        tk.Label(c, text="なにを連打する？（3つまで続けて送れます）",
                 bg=th.CARD, fg=th.INK, font=F["cute_b"]).pack(anchor="w")
        tk.Label(c, text="上から順に送ります。2つ目・3つ目が「なし」なら、"
                         "1つ目だけをくり返します",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=760,
                 justify="left").pack(anchor="w", pady=(0, 4))
        self.steps = []
        saved = list(cfg.get("macro_steps") or [])
        if not saved:      # 前のかたち（1行動だけ）から引き継ぐ
            saved = [{"action": cfg.get("macro_action") or macro.DEFAULT_ACTION,
                      "key_vk": cfg.get("macro_key_vk") or 0,
                      "key_scan": cfg.get("macro_key_scan") or 0,
                      "gap_ms": 120}]
        for i in range(macro.MAX_STEPS):
            self.steps.append(self._step_row(
                c, i, saved[i] if i < len(saved) else {}))

        trow = tk.Frame(c, bg=th.CARD)
        trow.pack(fill="x", pady=(6, 10))
        th.RoundButton(trow, "▶ ひと通りためす", self.test_once, kind="soft",
                       bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left")
        tk.Label(trow, text="「キー」を選んだときは、となりのボタンを押してから"
                           "使いたいキーを押してください",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(side="left",
                                                                  padx=6)

        n1 = tk.Frame(c, bg=th.CARD)
        n1.pack(fill="x", pady=2)
        tk.Label(n1, text="くり返す間隔", bg=th.CARD, fg=th.INK, font=F["cute"],
                 width=14, anchor="w").pack(side="left")
        self.v_interval = tk.StringVar(
            value=macro.fmt_secs(float(cfg.get("macro_interval_ms") or 100)
                                 / 1000.0))
        th.soft_entry(n1, self.v_interval, width=8).pack(side="left", ipady=3)
        tk.Label(n1, text=" ごと（0.5 / 2秒 / 1分30秒）", bg=th.CARD,
                 fg=th.INK_SUB, font=F["small"]).pack(side="left")
        for txt, ms in (("0.05", 50), ("0.1", 100), ("0.5", 500),
                        ("1秒", 1000), ("5秒", 5000), ("1分", 60000)):
            th.Chip(n1, txt, lambda v=ms: self._set_interval(v), bg=th.CARD,
                    font=F["small"]).pack(side="left", padx=2)

        n2 = tk.Frame(c, bg=th.CARD)
        n2.pack(fill="x", pady=2)
        tk.Label(n2, text="押している時間", bg=th.CARD, fg=th.INK, font=F["cute"],
                 width=14, anchor="w").pack(side="left")
        self.v_hold = tk.StringVar(value=str(int(cfg.get("macro_hold_ms") or 20)))
        th.soft_entry(n2, self.v_hold, width=7).pack(side="left", ipady=3)
        tk.Label(n2, text=" ミリ秒", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")

        n3 = tk.Frame(c, bg=th.CARD)
        n3.pack(fill="x", pady=(2, 10))
        tk.Label(n3, text="何回で止める", bg=th.CARD, fg=th.INK, font=F["cute"],
                 width=14, anchor="w").pack(side="left")
        self.v_limit = tk.StringVar(value=str(int(cfg.get("macro_limit") or 0)))
        th.soft_entry(n3, self.v_limit, width=7).pack(side="left", ipady=3)
        tk.Label(n3, text=" 回（0 でずっと）", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")

        tk.Label(c, text="どのアプリで動かす？", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        t1 = tk.Frame(c, bg=th.CARD)
        t1.pack(fill="x", pady=(4, 2))
        self.v_target = tk.StringVar(value=cfg.get("macro_target") or "")
        th.soft_entry(t1, self.v_target, width=24).pack(side="left", ipady=3)
        th.RoundButton(t1, "いま最前面のを使う", self.pick_foreground, kind="soft",
                       bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left", padx=6)
        self.lbl_found = tk.Label(t1, text="", bg=th.CARD, fg=th.INK_SUB,
                                  font=F["small"])
        self.lbl_found.pack(side="left")
        tk.Label(c, text="送り方", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w", pady=(8, 0))
        self.v_send = tk.StringVar(value=cfg.get("macro_send_mode")
                                   or macro.DEFAULT_SEND_MODE)
        for key, lbl in macro.SEND_MODES:
            tk.Radiobutton(c, text=lbl, variable=self.v_send, value=key,
                           command=self.save_send, bg=th.CARD, fg=th.INK,
                           activebackground=th.CARD, activeforeground=th.INK,
                           selectcolor=th.FIELD, font=F["cute"], bd=0,
                           highlightthickness=0, anchor="w").pack(anchor="w")
        tk.Label(c, text="⚠ ARKのようなゲームは「ウィンドウに直接送る」が効かない"
                         "ことがあります。「ためす」で確かめて、駄目なら"
                         "「一瞬だけ前に出して送る」を使ってください",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=760,
                 justify="left").pack(anchor="w", pady=(0, 8))

        self.v_rcancel = tk.BooleanVar(
            value=bool(cfg.get("macro_cancel_rclick", True)))
        self.chk_rcancel = tk.Checkbutton(
                       c, text="右クリックでとめる（連射・たまごの両方）",
                       variable=self.v_rcancel, command=self.save_rcancel,
                       bg=th.CARD, fg=th.INK, activebackground=th.CARD,
                       activeforeground=th.INK, selectcolor=th.FIELD,
                       font=F["cute"], bd=0, highlightthickness=0,
                       anchor="w")
        self.chk_rcancel.pack(anchor="w", pady=(6, 0))
        tk.Label(c, text="動かしているあいだだけ見張ります。ゲームが前に出ている"
                         "ときだけ効くので、ほかの作業中のクリックでは止まりません。"
                         "クリックそのものはゲームに届きますし、マクロが送った"
                         "クリックでも止まりません。"
                         "連射が右クリックのときは、代わりに左クリックで止まります",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=760,
                 justify="left").pack(anchor="w", pady=(0, 8))

        self.v_only = tk.BooleanVar(value=bool(cfg.get("macro_only_target", True)))
        self.chk_only = tk.Checkbutton(
                       c, text="このアプリが最前面のときだけ動かす"
                               "（連射・たまご・キャンセルの全部／おすすめ）",
                       variable=self.v_only, command=self.save, bg=th.CARD,
                       fg=th.INK, activebackground=th.CARD, activeforeground=th.INK,
                       selectcolor=th.FIELD, font=F["cute"], bd=0,
                       highlightthickness=0, anchor="w")
        self.chk_only.pack(anchor="w")
        tk.Label(c, text="⚠ 外すと、どの画面にいても動きます。押しっぱなし連打も"
                         "たまごマクロも、右クリックでのキャンセルも同じです。"
                         "デスクトップやエクスプローラーを触っていると危ないので、"
                         "基本は入れたままで",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=760,
                 justify="left").pack(anchor="w", pady=(0, 10))

        tk.Label(c, text="入切のショートカット", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        h1 = tk.Frame(c, bg=th.CARD)
        h1.pack(fill="x", pady=(4, 2))
        self.btn_hotkey = th.RoundButton(h1, "", self.capture_hotkey, kind="soft",
                                         bg=th.CARD, font=F["small"], padx=12,
                                         pady=5, width=190)
        self.btn_hotkey.pack(side="left")
        self.v_hk_on = tk.BooleanVar(value=bool(cfg.get("macro_hotkey_on", True)))
        tk.Checkbutton(h1, text="使う", variable=self.v_hk_on,
                       command=self.save_hotkey, bg=th.CARD, fg=th.INK,
                       activebackground=th.CARD, activeforeground=th.INK,
                       selectcolor=th.FIELD, font=F["cute"], bd=0,
                       highlightthickness=0).pack(side="left", padx=8)
        self.lbl_hk = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
                               font=F["small"], anchor="w", justify="left",
                               wraplength=760)
        self.lbl_hk.pack(fill="x")

        h2 = tk.Frame(c, bg=th.CARD)
        h2.pack(fill="x", pady=(6, 2))
        self.btn_hotkey2 = th.RoundButton(h2, "", self.capture_hotkey2,
                                          kind="soft", bg=th.CARD,
                                          font=F["small"], padx=12, pady=5,
                                          width=190)
        self.btn_hotkey2.pack(side="left")
        self.v_hk2_on = tk.BooleanVar(
            value=bool(cfg.get("macro2_hotkey_on", True)))
        tk.Checkbutton(h2, text="使う", variable=self.v_hk2_on,
                       command=self.save_hotkey, bg=th.CARD, fg=th.INK,
                       activebackground=th.CARD, activeforeground=th.INK,
                       selectcolor=th.FIELD, font=F["cute"], bd=0,
                       highlightthickness=0).pack(side="left", padx=8)
        self.lbl_hk2 = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="w", justify="left",
                                wraplength=760)
        self.lbl_hk2.pack(fill="x")

        h3 = tk.Frame(c, bg=th.CARD)
        h3.pack(fill="x", pady=(6, 2))
        self.btn_hotkey3 = th.RoundButton(h3, "", self.capture_hotkey3,
                                          kind="soft", bg=th.CARD,
                                          font=F["small"], padx=12, pady=5,
                                          width=190)
        self.btn_hotkey3.pack(side="left")
        self.v_hk3_on = tk.BooleanVar(
            value=bool(cfg.get("macro_hold_hotkey_on", True)))
        tk.Checkbutton(h3, text="使う", variable=self.v_hk3_on,
                       command=self.save_hotkey, bg=th.CARD, fg=th.INK,
                       activebackground=th.CARD, activeforeground=th.INK,
                       selectcolor=th.FIELD, font=F["cute"], bd=0,
                       highlightthickness=0).pack(side="left", padx=8)
        self.lbl_hk3 = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="w", justify="left",
                                wraplength=760)
        self.lbl_hk3.pack(fill="x")

        # ---------------- たまごマクロ（孵化器）----------------
        egg = th.Card(self.inner, bg=th.BG)
        egg.pack(fill="x", pady=(10, 0))
        e = egg.body
        tk.Label(e, text="🥚 たまごマクロ（孵化器）", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        tk.Label(e, text="「たまごを押す → 壊す／孵す を押す」の2回だけをくり返します。"
                         "1つ壊すと次のたまごが同じ場所へ繰り上がるので、"
                         "同じ2か所を押しつづければ全部さばけます。",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"], wraplength=760,
                 justify="left").pack(anchor="w", pady=(0, 6))

        r1 = tk.Frame(e, bg=th.CARD)
        r1.pack(fill="x")
        self.btn_learn = th.RoundButton(r1, "① 孵化をおぼえる",
                                        lambda: self.learn_egg("hatch"),
                                        kind="primary", bg=th.CARD,
                                        font=F["small"], padx=14, pady=6,
                                        width=180)
        self.btn_learn.pack(side="left")
        self.btn_learn_kill = th.RoundButton(r1, "① 破壊をおぼえる",
                                             lambda: self.learn_egg("destroy"),
                                             kind="danger", bg=th.CARD,
                                             font=F["small"], padx=14, pady=6,
                                             width=180)
        self.btn_learn_kill.pack(side="left", padx=6)
        self.lbl_learn = tk.Label(r1, text="", bg=th.CARD, fg=th.INK_SUB,
                                  font=F["small"], anchor="w", justify="left")
        self.lbl_learn.pack(side="left", padx=8)

        r2 = tk.Frame(e, bg=th.CARD)
        r2.pack(fill="x", pady=(6, 0))
        tk.Label(r2, text="たまごの数", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        self.v_slots = tk.StringVar(value=str(cfg.get("egg_slots",
                                                      macro.MAX_EGGS)))
        th.soft_entry(r2, self.v_slots, width=4).pack(side="left", padx=4,
                                                      ipady=3)
        tk.Label(r2, text="個（枠は%d個まで）　あいだ" % macro.MAX_EGGS,
                 bg=th.CARD, fg=th.INK, font=F["cute"]).pack(side="left")
        self.v_mid = tk.StringVar(
            value=macro.fmt_secs(float(cfg.get("egg_mid_ms", 150)) / 1000.0))
        th.soft_entry(r2, self.v_mid, width=7).pack(side="left", padx=4, ipady=3)
        tk.Label(r2, text="秒　次まで", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")
        self.v_egap = tk.StringVar(
            value=macro.fmt_secs(float(cfg.get("egg_gap_ms", 300)) / 1000.0))
        th.soft_entry(r2, self.v_egap, width=7).pack(side="left", padx=4,
                                                     ipady=3)
        tk.Label(r2, text="秒", bg=th.CARD, fg=th.INK,
                 font=F["cute"]).pack(side="left")

        r3 = tk.Frame(e, bg=th.CARD)
        r3.pack(fill="x", pady=(8, 0))
        self.btn_egg = th.RoundButton(r3, "▶ 孵化をはじめる",
                                      lambda: self.toggle_egg("hatch"),
                                      kind="mint", bg=th.CARD, font=F["small"],
                                      padx=14, pady=6, width=180)
        self.btn_egg.pack(side="left")
        self.btn_ehk = th.RoundButton(r3, "", self.capture_egg_hotkey,
                                      kind="soft", bg=th.CARD, font=F["small"],
                                      padx=12, pady=5, width=150)
        self.btn_ehk.pack(side="left", padx=6)
        self.v_ehk_on = tk.BooleanVar(value=bool(cfg.get("egg_hotkey_on", True)))
        tk.Checkbutton(r3, text="使う", variable=self.v_ehk_on,
                       command=self.save_egg_hotkey, bg=th.CARD, fg=th.INK,
                       activebackground=th.CARD, activeforeground=th.INK,
                       selectcolor=th.FIELD, font=F["cute"], bd=0,
                       highlightthickness=0).pack(side="left")

        r4 = tk.Frame(e, bg=th.CARD)
        r4.pack(fill="x", pady=(6, 0))
        self.btn_kill = th.RoundButton(r4, "▶ 破壊をはじめる",
                                       lambda: self.toggle_egg("destroy"),
                                       kind="danger", bg=th.CARD,
                                       font=F["small"], padx=14, pady=6,
                                       width=180)
        self.btn_kill.pack(side="left")
        self.btn_khk = th.RoundButton(r4, "", self.capture_kill_hotkey,
                                      kind="soft", bg=th.CARD, font=F["small"],
                                      padx=12, pady=5, width=150)
        self.btn_khk.pack(side="left", padx=6)
        self.v_khk_on = tk.BooleanVar(
            value=bool(cfg.get("egg_kill_hotkey_on", True)))
        tk.Checkbutton(r4, text="使う", variable=self.v_khk_on,
                       command=self.save_egg_hotkey, bg=th.CARD, fg=th.INK,
                       activebackground=th.CARD, activeforeground=th.INK,
                       selectcolor=th.FIELD, font=F["cute"], bd=0,
                       highlightthickness=0).pack(side="left")
        tk.Label(r4, text="  ⚠ 破壊は戻せません。位置をよく確かめてから",
                 bg=th.CARD, fg=th.PINK_DK, font=F["small"]).pack(side="left")
        self.lbl_egg = tk.Label(e, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="w", justify="left",
                                wraplength=760)
        self.lbl_egg.pack(fill="x", pady=(4, 0))
        for v in (self.v_slots, self.v_mid, self.v_egap):
            v.trace_add("write", lambda *a: self.save_egg())

        for v in (self.v_interval, self.v_hold, self.v_limit, self.v_target):
            v.trace_add("write", lambda *a: self.save())
        self.update_view()

    # ---------------- 設定 ----------------
    def _step_row(self, parent, i, st):
        """行動ひとつぶんの列。種類・キー・次までの間隔。"""
        F = self.F
        row = tk.Frame(parent, bg=th.CARD)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="%d つ目" % (i + 1), bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"], width=6, anchor="w").pack(side="left")
        v_act = tk.StringVar()
        cb = ttk.Combobox(row, textvariable=v_act, state="readonly", width=16,
                          style="Cute.TCombobox", font=F["ui"])
        vals = [lbl for _k, lbl in macro.ACTIONS]
        if i > 0:
            vals = ["なし"] + vals      # 2つ目からは「使わない」が選べる
        cb["values"] = vals
        act = (st.get("action") or "").strip()
        if i > 0 and not act:
            v_act.set("なし")
        else:
            v_act.set(macro.action_label(act or macro.DEFAULT_ACTION))
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.save())

        btn = th.RoundButton(row, "", lambda n=i: self.capture_key(n),
                             kind="soft", bg=th.CARD, font=F["small"],
                             padx=12, pady=5, width=170)
        btn.pack(side="left", padx=6)
        tk.Label(row, text="次まで", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")
        v_gap = tk.StringVar(
            value=macro.fmt_secs(float(st.get("gap_ms", 120)) / 1000.0))
        e = th.soft_entry(row, v_gap, width=8)
        e.pack(side="left", padx=4, ipady=3)
        e.bind("<FocusOut>", lambda ev: self.save())
        return {"act": v_act, "cb": cb, "btn": btn, "gap": v_gap,
                "vk": int(st.get("key_vk") or 0),
                "scan": int(st.get("key_scan") or 0)}

    def step_name(self, i):
        """i つ目に選ばれている種類。「なし」なら空。"""
        want = self.steps[i]["act"].get()
        if want == "なし":
            return ""
        for k, lbl in macro.ACTIONS:
            if lbl == want:
                return k
        return macro.DEFAULT_ACTION

    def _int(self, var, default, lo, hi):
        try:
            return max(lo, min(hi, int(float(var.get()))))
        except ValueError:
            return default

    def _set_interval(self, ms):
        self.v_interval.set(macro.fmt_secs(ms / 1000.0))

    def _secs_ms(self, var, key, default_ms, lo_ms, hi_ms):
        """秒で書かれた欄を、ミリ秒にして返す。

        読めない字が入っていたら、**いまの設定のまま**にする。
        工場出荷の値に戻してしまうと、打ち間違いで設定が消える。
        """
        now = self.app.cfg.get(key, default_ms) if key else default_ms
        got = macro.parse_secs(var.get(), None)
        if got is None:
            return now
        return max(lo_ms, min(hi_ms, int(round(got * 1000))))

    def steps_cfg(self):
        """画面の3列を、しまえるかたちにする。「なし」は落とす。"""
        out = []
        for i, st in enumerate(self.steps):
            act = self.step_name(i)
            if not act:
                continue
            gap = self._secs_ms(st["gap"], "",
                                int(st.get("gap_ms") or 120), 0, 600000)
            st["gap_ms"] = gap          # 打ち間違えても前の値に戻れるように
            out.append({"action": act, "key_vk": st["vk"],
                        "key_scan": st["scan"], "gap_ms": gap})
        return out

    def save(self):
        c = self.app.cfg
        steps = self.steps_cfg()
        c["macro_steps"] = steps
        # 1つ目は、前のかたちの設定にも書いておく（他の画面がまだ見ている）
        head = steps[0] if steps else {}
        c["macro_action"] = head.get("action") or macro.DEFAULT_ACTION
        c["macro_key_vk"] = head.get("key_vk") or 0
        c["macro_key_scan"] = head.get("key_scan") or 0
        c["macro_interval_ms"] = self._secs_ms(
            self.v_interval, "macro_interval_ms", 100, 1, 3600000)
        c["macro_hold_ms"] = self._int(self.v_hold, 20, 0, 5000)
        try:
            c["macro_hold_delay_ms"] = max(0, min(
                5000, int(float(self.v_delay.get()) * 1000)))
        except (TypeError, ValueError):
            pass                    # 数字でなければ前のままにしておく
        c["macro_limit"] = self._int(self.v_limit, 0, 0, 1000000)
        c["macro_target"] = self.v_target.get().strip()
        c["macro_only_target"] = bool(self.v_only.get())
        c["macro_send_mode"] = self.v_send.get()
        self.update_view()

    def save_badge(self):
        self.app.cfg["macro_badge"] = bool(self.v_badge.get())
        self.app.save_cfg()
        self.app._badge_tick()

    def save_blip(self):
        self.app.cfg["blip"] = bool(self.v_blip.get())
        self.app.save_cfg()
        if self.v_blip.get():
            self.app.blip("こんな感じで出ます")

    def save_send(self):
        """送り方を変える。裏へ送るときは「最前面のときだけ」は要らない。"""
        self.save()
        direct = self.v_send.get() != "input"
        if direct and self.v_only.get():
            self.v_only.set(False)      # 裏へ送るのに前面待ちしたら意味がない
            self.save()
        self.chk_only.config(state="disabled" if direct else "normal")
        self.update_view()

    def save_hotkey(self):
        """3本のショートカットの「使う／使わない」をまとめて入れ直す。"""
        c = self.app.cfg
        c["macro_hotkey_on"] = bool(self.v_hk_on.get())
        c["macro2_hotkey_on"] = bool(self.v_hk2_on.get())
        c["macro_hold_hotkey_on"] = bool(self.v_hk3_on.get())
        self.app.save_cfg()
        self.app.apply_hotkey()
        self.update_view()

    def pick_foreground(self):
        self.app.after(1500, self._pick_now)
        self.lbl_sub.config(text="1.5秒以内に対象のウィンドウをクリックしてください…")

    def _pick_now(self):
        import afk
        name = afk.foreground_exe()
        if name and name.lower() != "arkbreedingtimer.exe":
            self.v_target.set(name)
        self.update_view()

    # ---------------- キーの取り込み ----------------
    def capture_key(self, i=0):
        self._capture("key%d" % i)

    def capture_hotkey(self):
        self._capture("hotkey")

    def capture_hotkey2(self):
        self._capture("hotkey2")

    def capture_hotkey3(self):
        self._capture("hotkey3")

    def _capture(self, what):
        if self._capturing:
            self._end_capture()        # もう一度押したらやめる
            return
        self._capturing = what
        if what.startswith("key"):
            btn = self.steps[int(what[3:])]["btn"]
        else:
            btn = {"hotkey": self.btn_hotkey, "hotkey2": self.btn_hotkey2,
                   "hotkey3": self.btn_hotkey3, "egg_hotkey": self.btn_ehk,
                   "kill_hotkey": self.btn_khk}[what]
        btn.set_text("キーを押してください…（Escでやめる）")
        top = self.winfo_toplevel()
        # Alt の組み合わせは Windows がシステムキー扱いにするので、
        # ふつうの <KeyPress> には来ない。<Alt-KeyPress> も一緒に押さえる。
        self._bind_ids = [
            ("<KeyPress>", top.bind("<KeyPress>", self._on_capture_key,
                                    add="+")),
            ("<Alt-KeyPress>", top.bind("<Alt-KeyPress>", self._on_capture_key,
                                        add="+")),
        ]
        top.focus_force()

    def _end_capture(self):
        self._capturing = False
        top = self.winfo_toplevel()
        for seq, bid in getattr(self, "_bind_ids", []):
            try:
                top.unbind(seq, bid)
            except tk.TclError:
                pass
        self._bind_ids = []
        self.update_view()

    def _on_capture_key(self, e):
        if not self._capturing:
            return None
        vk = e.keycode        # Windows では仮想キーコードがそのまま入る
        if vk in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B):
            return "break"    # 修飾キー単体は無視して、本命のキーを待つ
        if vk == 0x1B:        # Esc
            self._end_capture()
            return "break"
        what = self._capturing
        self._end_capture()
        if what.startswith("key"):
            st = self.steps[int(what[3:])]
            st["vk"], st["scan"] = vk, macro.scancode_of(vk)
            self.save()
            self.app.save_cfg()
        else:
            # 押しているキーそのものを見る（NumLock を Alt と読み違えない）
            mods = macro.mods_now()
            if not mods:
                mods = macro.MOD_CONTROL   # 修飾なしは事故のもとなので Ctrl を足す
            if what in ("egg_hotkey", "kill_hotkey"):
                head = "egg_kill_hotkey" if what == "kill_hotkey" \
                    else "egg_hotkey"
                self.app.cfg[head + "_mods"] = mods
                self.app.cfg[head + "_vk"] = vk
                self.app.save_cfg()
                self.app.apply_egg_hotkey()
            else:
                head = {"hotkey2": "macro2_hotkey",
                        "hotkey3": "macro_hold_hotkey"}.get(what,
                                                            "macro_hotkey")
                self.app.cfg[head + "_mods"] = mods
                self.app.cfg[head + "_vk"] = vk
                self.app.save_cfg()
                self.app.apply_hotkey()
        self.update_view()
        return "break"

    def _wheel(self, e):
        """マクロのページを見ているときだけホイールで動かす。"""
        try:
            if self.winfo_ismapped():
                self.canvas.yview_scroll(int(-e.delta / 120), "units")
        except tk.TclError:
            pass

    # ---------------- たまごマクロ ----------------
    def update_egg_view(self):
        """たまごマクロの見た目を今の状態に合わせる。"""
        c = self.app.cfg
        egg = c.get("egg_pos")
        hatch, kill = c.get("egg_act_pos"), c.get("egg_kill_pos")
        if self.app.egg_rec is None:
            bits = []
            if egg and hatch:
                bits.append("孵化 → (%d, %d)" % (hatch[0], hatch[1]))
            if egg and kill:
                bits.append("破壊 → (%d, %d)" % (kill[0], kill[1]))
            if bits:
                self.lbl_learn.config(
                    text="✅ たまご(%d, %d) ／ %s" % (egg[0], egg[1],
                                                     "／ ".join(bits)),
                    fg=th.MINT)
            else:
                self.lbl_learn.config(text="まだ覚えていません", fg=th.INK_SUB)
            self.btn_learn.set_text("① 孵化をおぼえ%s"
                                    % ("なおす" if (egg and hatch) else "る"))
            self.btn_learn_kill.set_text("① 破壊をおぼえ%s"
                                         % ("なおす" if (egg and kill) else "る"))
        name = macro.hotkey_name(c.get("egg_hotkey_mods", macro.MOD_CONTROL),
                                 c.get("egg_hotkey_vk", 0x45))
        kname = macro.hotkey_name(
            c.get("egg_kill_hotkey_mods", macro.MOD_CONTROL),
            c.get("egg_kill_hotkey_vk", 0x4C))
        if self._capturing != "egg_hotkey":
            self.btn_ehk.set_text(name)
        if self._capturing != "kill_hotkey":
            self.btn_khk.set_text(kname)
        running = self.app.egg_running()
        mode = self.app.egg_mode
        self.btn_egg.set_text("■ とめる" if (running and mode == "hatch")
                              else "▶ 孵化をはじめる")
        self.btn_kill.set_text("■ とめる" if (running and mode == "destroy")
                               else "▶ 破壊をはじめる")
        slots = c.get("egg_slots", macro.MAX_EGGS)
        r = self.app.egg
        if running:
            what = "破壊" if mode == "destroy" else "孵化"
            if r is not None and r.waiting:
                txt = "%s待ち（%s）" % (what, c.get("macro_target") or "対象")
            else:
                txt = "%s中 — %d / %d 個" % (what, r.count if r else 0, slots)
            self.lbl_egg.config(text=txt, fg=th.MINT)
        elif self.app._egg_hotkey_err:
            self.lbl_egg.config(text="⚠ %s が使えません（%s）。別の組み合わせに"
                                     "してください" % (name,
                                                     self.app._egg_hotkey_err),
                                fg=th.PINK_DK)
        elif r is not None and r.finished and r.count:
            self.lbl_egg.config(text="✅ %d個ぶん終わりました" % r.count,
                                fg=th.MINT)
        else:
            mode = macro.send_mode_label(c.get("macro_send_mode")
                                         or macro.DEFAULT_SEND_MODE)
            self.lbl_egg.config(
                text="%d個ぶん ／ 孵化 %s・破壊 %s で入切 ／ 送り方: %s"
                     % (slots, name, kname, mode), fg=th.INK_SUB)

    def save_rcancel(self):
        self.app.cfg["macro_cancel_rclick"] = bool(self.v_rcancel.get())
        self.app.save_cfg()
        self.app.sync_cancel_watch()
        self.update_view()

    def save_egg(self):
        c = self.app.cfg
        c["egg_slots"] = self._int(self.v_slots, macro.MAX_EGGS, 1,
                                   macro.MAX_EGGS)
        c["egg_mid_ms"] = self._secs_ms(self.v_mid, "egg_mid_ms", 150, 0, 60000)
        c["egg_gap_ms"] = self._secs_ms(self.v_egap, "egg_gap_ms", 300, 0, 60000)
        self.app.save_cfg()
        self.update_view()

    def learn_egg(self, mode="hatch"):
        """次の2クリックを覚える。ゲーム画面で実際にやってもらう。"""
        if self.app.egg_rec is not None and self.app.egg_rec.is_alive():
            self.app.egg_rec.stop()
            self.app.egg_rec = None
            self.lbl_learn.config(text="やめました", fg=th.INK_SUB)
            self.update_view()
            return
        self._learn_mode = mode
        self.app.cfg[self.app.egg_act_key(mode)] = None
        rec = macro.ClickRecorder(2)
        self.app.egg_rec = rec
        rec.start()
        what = "壊す" if mode == "destroy" else "孵す"
        (self.btn_learn_kill if mode == "destroy"
         else self.btn_learn).set_text("やめる")
        self.lbl_learn.config(text="ARKへ行って、たまごを1つクリック → "
                                  "「%s」をクリックしてください" % what,
                              fg=th.INK)
        self._poll_learn()

    def _poll_learn(self):
        """記録係は別スレッドなので、こちらから様子を見に行く。"""
        rec = self.app.egg_rec
        if rec is None:
            return
        n = len(rec.points)
        mode = getattr(self, "_learn_mode", "hatch")
        if rec.done and n >= 2:
            self.app.cfg["egg_pos"] = list(rec.points[0])
            self.app.cfg[self.app.egg_act_key(mode)] = list(rec.points[1])
            self.app.save_cfg()
            self.app.egg_rec = None
            self.lbl_learn.config(
                text="✅ %s を覚えました" % ("破壊" if mode == "destroy"
                                             else "孵化"), fg=th.MINT)
            self.update_view()
            return
        if not rec.is_alive():
            self.app.egg_rec = None
            self.update_view()
            return
        self.lbl_learn.config(
            text=("たまごをクリックしてください（あと2回）" if n == 0 else
                  "つぎに「%s」をクリック（あと1回）"
                  % ("壊す" if mode == "destroy" else "孵す")), fg=th.INK)
        self.after(120, self._poll_learn)

    def toggle_egg(self, mode="hatch"):
        c = self.app.cfg
        if not (c.get("egg_pos") and c.get(self.app.egg_act_key(mode))):
            self.lbl_egg.config(
                text="⚠ さきに「① %sをおぼえる」で2か所を覚えさせてください"
                     % ("破壊" if mode == "destroy" else "孵化"),
                fg=th.PINK_DK)
            return
        self.save_egg()
        self.app.toggle_egg(mode)
        self.update_view()

    def capture_kill_hotkey(self):
        self._capture("kill_hotkey")

    def save_egg_hotkey(self):
        self.app.cfg["egg_hotkey_on"] = bool(self.v_ehk_on.get())
        self.app.cfg["egg_kill_hotkey_on"] = bool(self.v_khk_on.get())
        self.app.save_cfg()
        self.app.apply_egg_hotkey()
        self.update_view()

    def capture_egg_hotkey(self):
        self._capture("egg_hotkey")

    def test_once(self):
        """設定どおりに1回だけ送る（対象チェックはしない）。"""
        self.save()
        c = self.app.cfg
        ok, why = macro.send_seq({
            "send_mode": c.get("macro_send_mode") or macro.DEFAULT_SEND_MODE,
            "steps": c.get("macro_steps") or [],
            "hold_ms": c.get("macro_hold_ms", 20),
            "target": c.get("macro_target") or ""})
        if why:
            self.lbl_sub.config(text="⚠ " + why)
            return
        what = (macro.vk_name(c.get("macro_key_vk") or 0) if act == "key"
                else macro.action_label(act))
        self.lbl_sub.config(
            text=("✅ %s を1回送りました" % what) if ok else "⚠ 送れませんでした")

    # ---------------- 入切 ----------------
    def toggle_hold(self):
        self.save()
        self.app.toggle_hold()
        self.update_view()

    def toggle(self, mode="hold"):
        self.save()
        self.app.toggle_macro(mode)
        self.update_view()

    def update_view(self, now=None):
        cfg = self.app.cfg
        running = self.app.macro_running()
        hold = running and self.app.macro_mode() == "hold"
        always = running and not hold
        self.btn.set_text("■ とめる" if hold else "▶ かまえる")
        self.btn_always.set_text("■ とめる" if always else "▶ ずっと連射")
        pressing = self.app.holder_running()
        self.btn_press.set_text("■ 離す" if pressing else "⬇ 長押し")
        only = cfg.get("macro_only_target", True)
        self.lbl_mode.config(text=" ／ ".join((
            "かまえる … 左クリックを押しているあいだだけ連打",
            "ずっと連射 … 手を離していても送りつづける",
            "長押し … 連打せず、押したままにする（採取や走りっぱなしに）",
            ("下で決めたアプリが前に出ているときだけ動きます" if only
             else "⚠ 最前面しばりを外しているので、どの画面でも動きます"),
        )))

        # キー指定ボタンの文字（その行が「キー」のときだけ意味がある）。
        # キー待ちのあいだは書き換えない。毎秒ここが走るので、上書きすると
        # 「押した瞬間に戻る」ように見えてしまう。
        vk = cfg.get("macro_key_vk") or 0
        for i, st in enumerate(self.steps):
            if self._capturing == "key%d" % i:
                continue
            if self.step_name(i) == "key":
                st["btn"].set_text("キー: %s" % macro.vk_name(st["vk"]))
            elif self.step_name(i):
                st["btn"].set_text("（キーのときだけ）")
            else:
                st["btn"].set_text("")
        if self._capturing != "hotkey":
            self.btn_hotkey.set_text("%s ▸ 変える" % macro.hotkey_name(
                cfg.get("macro_hotkey_mods", macro.MOD_CONTROL),
                cfg.get("macro_hotkey_vk", 0x52)))
        if self._capturing != "hotkey2":
            self.btn_hotkey2.set_text("%s ▸ 変える" % macro.hotkey_name(
                cfg.get("macro2_hotkey_mods", macro.MOD_CONTROL),
                cfg.get("macro2_hotkey_vk", 0x54)))
        if self._capturing != "hotkey3":
            self.btn_hotkey3.set_text("%s ▸ 変える" % macro.hotkey_name(
                cfg.get("macro_hold_hotkey_mods", macro.MOD_CONTROL),
                cfg.get("macro_hold_hotkey_vk", 0x4B)))

        self.chk_rcancel.config(
            text="%sクリックでとめる（連射・たまごの両方）"
                 % ("左" if self.app.cancel_button() == "left" else "右"))
        st = self.app.hotkey_status("hold")
        self.lbl_hk.config(text=st,
                           fg=th.PINK_DK if st.startswith("⚠") else th.INK_SUB)
        st2 = self.app.hotkey_status("always")
        self.lbl_hk2.config(text=st2,
                            fg=th.PINK_DK if st2.startswith("⚠") else th.INK_SUB)
        st3 = self.app.hotkey_status("press")
        self.lbl_hk3.config(text=st3,
                            fg=th.PINK_DK if st3.startswith("⚠") else th.INK_SUB)
        self.update_egg_view()

        act = cfg.get("macro_action") or macro.DEFAULT_ACTION
        what = macro.vk_name(vk) if act == "key" else macro.action_label(act)
        target = cfg.get("macro_target") or ""

        # 対象アプリの今の様子（名前が合っているか一目で分かるように）
        if not target:
            self.lbl_found.config(text="  （空 = どこでも動きます）", fg=th.PINK_DK)
        elif afk.matches(target):
            self.lbl_found.config(text="  ✅ いま最前面です", fg=th.MINT)
        elif afk.find_window_cached(target):
            self.lbl_found.config(text="  ⏸ 起動中（前に出れば動きます）",
                                  fg=th.INK_SUB)
        else:
            self.lbl_found.config(text="  ⚠ 見つかりません", fg=th.PINK_DK)

        if pressing:
            h = self.app.holder
            if h is not None and h.waiting:
                self.lbl_state.config(text="待機中（%s が前に出るまで）"
                                           % (target or "対象"), fg=th.INK_SUB)
            else:
                self.lbl_state.config(text="長押し中！", fg=th.MINT)
            self.lbl_sub.config(text="%s を押したままにしています。"
                                     "もう一度押すと離します" % what)
            return
        if not running:
            just = (self.app.cancelled_at
                    and time.time() - self.app.cancelled_at < 6)
            self.lbl_state.config(
                text="右クリックでとめました" if just else "とまっています",
                fg=th.PINK_DK if just else th.INK_SUB)
            self.lbl_sub.config(text="%s を %dミリ秒ごとに送ります" % (
                what, cfg.get("macro_interval_ms", 100)))
            return
        r = self.app.macro
        if hold and r is not None and not r.holding:
            self.lbl_state.config(text="かまえ中（左クリックを押しっぱなしで連打）",
                                  fg=th.INK_SUB)
        elif r is not None and r.waiting:
            # 直送りのときは前面待ちではなく「窓が見つからない」で止まっている
            why = ("が見つかるまで" if cfg.get("macro_send_mode", "input") != "input"
                   else "が前に出るまで")
            self.lbl_state.config(text="待機中（%s %s）" % (target, why),
                                  fg=th.INK_SUB)
        else:
            self.lbl_state.config(text="連打中！", fg=th.MINT)
        limit = int(cfg.get("macro_limit") or 0)
        n = r.count if r is not None else 0
        self.lbl_sub.config(text="%s を %d回 送りました%s" % (
            what, n, ("／ %d回で止まります" % limit) if limit else ""))
