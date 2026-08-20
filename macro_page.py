# -*- coding: utf-8 -*-
"""🖱 マクロのページ。連射の設定と入切。実際の送信は macro.py。"""
from __future__ import annotations

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
        F = app.F
        cfg = app.cfg

        # ---- 上: スイッチと状態 ----
        top = th.Card(self, bg=th.BG)
        top.pack(fill="x")
        b = top.body
        row = tk.Frame(b, bg=th.CARD)
        row.pack(fill="x")
        self.btn = th.RoundButton(row, "▶ はじめる", self.toggle, kind="primary",
                                  bg=th.CARD, font=F["cute_b"], padx=26)
        self.btn.pack(side="left")
        self.lbl_state = tk.Label(row, text="", bg=th.CARD, fg=th.INK,
                                  font=F["cute"], anchor="w")
        self.lbl_state.pack(side="left", padx=14)
        self.lbl_sub = tk.Label(b, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="w", justify="left")
        self.lbl_sub.pack(fill="x", pady=(8, 0))

        # ---- 下: 設定 ----
        conf = th.Card(self, bg=th.BG)
        conf.pack(fill="x", pady=(8, 0))
        c = conf.body

        tk.Label(c, text="なにを連打する？", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        arow = tk.Frame(c, bg=th.CARD)
        arow.pack(fill="x", pady=(4, 2))
        self.v_action = tk.StringVar(
            value=macro.action_label(cfg.get("macro_action")))
        self.cb_action = ttk.Combobox(arow, textvariable=self.v_action,
                                      state="readonly", width=18,
                                      style="Cute.TCombobox", font=F["ui"])
        self.cb_action["values"] = [lbl for _k, lbl in macro.ACTIONS]
        self.cb_action.pack(side="left")
        self.cb_action.bind("<<ComboboxSelected>>", lambda e: self.save())
        self.btn_key = th.RoundButton(arow, "", self.capture_key, kind="soft",
                                      bg=th.CARD, font=F["small"], padx=12,
                                      pady=5, width=190)
        self.btn_key.pack(side="left", padx=6)
        th.RoundButton(arow, "▶ 1回ためす", self.test_once, kind="soft", bg=th.CARD,
                       font=F["small"], padx=12, pady=5).pack(side="left")
        tk.Label(c, text="「キー」を選んだときは、右のボタンを押してから"
                         "使いたいキーを押してください",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w",
                                                                  pady=(0, 10))

        n1 = tk.Frame(c, bg=th.CARD)
        n1.pack(fill="x", pady=2)
        tk.Label(n1, text="間隔", bg=th.CARD, fg=th.INK, font=F["cute"],
                 width=14, anchor="w").pack(side="left")
        self.v_interval = tk.StringVar(
            value=str(int(cfg.get("macro_interval_ms") or 100)))
        th.soft_entry(n1, self.v_interval, width=7).pack(side="left", ipady=3)
        tk.Label(n1, text=" ミリ秒ごと", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")
        for txt, ms in (("50", 50), ("100", 100), ("200", 200), ("500", 500),
                        ("1000", 1000)):
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

        self.v_only = tk.BooleanVar(value=bool(cfg.get("macro_only_target", True)))
        self.chk_only = tk.Checkbutton(
                       c, text="このアプリが最前面のときだけ動かす（おすすめ）",
                       variable=self.v_only, command=self.save, bg=th.CARD,
                       fg=th.INK, activebackground=th.CARD, activeforeground=th.INK,
                       selectcolor=th.FIELD, font=F["cute"], bd=0,
                       highlightthickness=0, anchor="w")
        self.chk_only.pack(anchor="w")
        tk.Label(c, text="⚠ 外すと、どの画面にいても連打します。"
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

        for v in (self.v_interval, self.v_hold, self.v_limit, self.v_target):
            v.trace_add("write", lambda *a: self.save())
        self.update_view()

    # ---------------- 設定 ----------------
    def _int(self, var, default, lo, hi):
        try:
            return max(lo, min(hi, int(float(var.get()))))
        except ValueError:
            return default

    def _set_interval(self, ms):
        self.v_interval.set(str(ms))

    def action_name(self):
        label = self.v_action.get()
        for k, lbl in macro.ACTIONS:
            if lbl == label:
                return k
        return macro.DEFAULT_ACTION

    def save(self):
        c = self.app.cfg
        c["macro_action"] = self.action_name()
        c["macro_interval_ms"] = self._int(self.v_interval, 100, 1, 600000)
        c["macro_hold_ms"] = self._int(self.v_hold, 20, 0, 5000)
        c["macro_limit"] = self._int(self.v_limit, 0, 0, 1000000)
        c["macro_target"] = self.v_target.get().strip()
        c["macro_only_target"] = bool(self.v_only.get())
        c["macro_send_mode"] = self.v_send.get()
        self.update_view()

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
        self.app.cfg["macro_hotkey_on"] = bool(self.v_hk_on.get())
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
    def capture_key(self):
        self._capture("key")

    def capture_hotkey(self):
        self._capture("hotkey")

    def _capture(self, what):
        if self._capturing:
            return
        self._capturing = what
        btn = self.btn_key if what == "key" else self.btn_hotkey
        btn.set_text("キーを押してください…")
        top = self.winfo_toplevel()
        self._bind_id = top.bind("<KeyPress>", self._on_capture_key, add="+")
        top.focus_force()

    def _on_capture_key(self, e):
        if not self._capturing:
            return
        vk = e.keycode        # Windows では仮想キーコードがそのまま入る
        if vk in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B):
            return "break"    # 修飾キー単体は無視して、本命のキーを待つ
        what, self._capturing = self._capturing, False
        self.winfo_toplevel().unbind("<KeyPress>", self._bind_id)
        if what == "key":
            self.app.cfg["macro_key_vk"] = vk
            self.app.cfg["macro_key_scan"] = macro.scancode_of(vk)
        else:
            mods = 0
            if e.state & 0x0004:
                mods |= macro.MOD_CONTROL
            if e.state & 0x0001:
                mods |= macro.MOD_SHIFT
            if e.state & 0x20000 or e.state & 0x0008:
                mods |= macro.MOD_ALT
            if not mods:
                mods = macro.MOD_CONTROL   # 修飾なしは事故のもとなので Ctrl を足す
            self.app.cfg["macro_hotkey_mods"] = mods
            self.app.cfg["macro_hotkey_vk"] = vk
            self.app.apply_hotkey()
        self.update_view()
        return "break"

    def test_once(self):
        """設定どおりに1回だけ送る（対象チェックはしない）。"""
        self.save()
        c = self.app.cfg
        act = self.action_name()
        ok, why = macro.send_once({
            "send_mode": c.get("macro_send_mode") or macro.DEFAULT_SEND_MODE,
            "action": act, "key_vk": c.get("macro_key_vk") or 0,
            "key_scan": c.get("macro_key_scan") or 0,
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
    def toggle(self):
        self.save()
        self.app.toggle_macro()
        self.update_view()

    def update_view(self, now=None):
        cfg = self.app.cfg
        running = self.app.macro_running()
        self.btn.set_text("■ とめる" if running else "▶ はじめる")

        # キー指定ボタンの文字（アクションが「キー」のときだけ意味がある）
        vk = cfg.get("macro_key_vk") or 0
        self.btn_key.set_text("キー: %s" % macro.vk_name(vk))
        self.btn_hotkey.set_text("%s ▸ 変える" % macro.hotkey_name(
            cfg.get("macro_hotkey_mods", macro.MOD_CONTROL),
            cfg.get("macro_hotkey_vk", 0x52)))

        st = self.app.hotkey_status()
        self.lbl_hk.config(text=st, fg=th.PINK_DK if st.startswith("⚠") else th.INK_SUB)

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

        if not running:
            self.lbl_state.config(text="とまっています", fg=th.INK_SUB)
            self.lbl_sub.config(text="%s を %dミリ秒ごとに送ります" % (
                what, cfg.get("macro_interval_ms", 100)))
            return
        r = self.app.macro
        if r is not None and r.waiting:
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
