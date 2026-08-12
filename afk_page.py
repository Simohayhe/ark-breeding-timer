# -*- coding: utf-8 -*-
"""🎮 AFK防止のページ。

放置キック対策として、決めた間隔でキーを送る。実際の送信は afk.py。
このファイルは画面と設定だけを持つ。
"""
from __future__ import annotations

import time
import tkinter as tk

import afk
import theme as th


class AfkPage(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=th.BG)
        self.app = app
        F = app.F

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
                                  font=F["cute"], anchor="w", justify="left")
        self.lbl_state.pack(side="left", padx=14)
        self.lbl_sub = tk.Label(b, text="", bg=th.CARD, fg=th.INK_SUB,
                                font=F["small"], anchor="w", justify="left")
        self.lbl_sub.pack(fill="x", pady=(8, 0))

        # ---- 下: 設定 ----
        conf = th.Card(self, bg=th.BG)
        conf.pack(fill="x", pady=(8, 0))
        c = conf.body
        cfg = app.cfg

        tk.Label(c, text="どのキーを送る？", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        krow = tk.Frame(c, bg=th.CARD)
        krow.pack(fill="x", pady=(4, 2))
        self.key_names = [k for k, _ in afk.key_choices()]
        self.v_key = tk.StringVar(value=afk.key_label(cfg.get("afk_key")))
        from tkinter import ttk
        self.cb_key = ttk.Combobox(krow, textvariable=self.v_key, state="readonly",
                                   width=22, style="Cute.TCombobox", font=F["ui"])
        self.cb_key["values"] = [lbl for _k, lbl in afk.key_choices()]
        self.cb_key.pack(side="left")
        self.cb_key.bind("<<ComboboxSelected>>", lambda e: self.save())
        th.RoundButton(krow, "▶ ためす", self.test_once, kind="soft", bg=th.CARD,
                       font=F["small"], padx=12, pady=5).pack(side="left", padx=6)
        tk.Label(c, text="ARKで押しても困らないキーを選んでください。"
                         "スペース（その場でジャンプ）が無難です",
                 bg=th.CARD, fg=th.INK_SUB, font=F["small"]).pack(anchor="w",
                                                                  pady=(0, 10))

        n1 = tk.Frame(c, bg=th.CARD)
        n1.pack(fill="x", pady=2)
        tk.Label(n1, text="何秒ごとに送る", bg=th.CARD, fg=th.INK, font=F["cute"],
                 width=16, anchor="w").pack(side="left")
        self.v_interval = tk.StringVar(value=str(int(cfg.get("afk_interval") or 120)))
        th.soft_entry(n1, self.v_interval, width=6).pack(side="left", ipady=3)
        tk.Label(n1, text=" 秒", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")

        n2 = tk.Frame(c, bg=th.CARD)
        n2.pack(fill="x", pady=2)
        tk.Label(n2, text="1回に何連打", bg=th.CARD, fg=th.INK, font=F["cute"],
                 width=16, anchor="w").pack(side="left")
        self.v_times = tk.StringVar(value=str(int(cfg.get("afk_times") or 1)))
        th.soft_entry(n2, self.v_times, width=6).pack(side="left", ipady=3)
        tk.Label(n2, text=" 回", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")

        n3 = tk.Frame(c, bg=th.CARD)
        n3.pack(fill="x", pady=(2, 10))
        tk.Label(n3, text="連打の間隔", bg=th.CARD, fg=th.INK, font=F["cute"],
                 width=16, anchor="w").pack(side="left")
        self.v_gap = tk.StringVar(value=str(int(cfg.get("afk_gap_ms") or 60)))
        th.soft_entry(n3, self.v_gap, width=6).pack(side="left", ipady=3)
        tk.Label(n3, text=" ミリ秒", bg=th.CARD, fg=th.INK_SUB,
                 font=F["small"]).pack(side="left")

        tk.Label(c, text="どのアプリに送る？", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w")
        t1 = tk.Frame(c, bg=th.CARD)
        t1.pack(fill="x", pady=(4, 6))
        self.v_target = tk.StringVar(value=cfg.get("afk_target") or "")
        th.soft_entry(t1, self.v_target, width=24).pack(side="left", ipady=3)
        th.RoundButton(t1, "いま最前面のを使う", self.pick_foreground, kind="soft",
                       bg=th.CARD, font=F["small"], padx=12,
                       pady=5).pack(side="left", padx=6)
        self.lbl_found = tk.Label(t1, text="", bg=th.CARD, fg=th.INK_SUB,
                                  font=F["small"])
        self.lbl_found.pack(side="left")

        tk.Label(c, text="送りかた", bg=th.CARD, fg=th.INK,
                 font=F["cute_b"]).pack(anchor="w", pady=(6, 0))
        self.v_mode = tk.StringVar(value=cfg.get("afk_mode") or afk.DEFAULT_MODE)
        for key, label in afk.MODES:
            tk.Radiobutton(c, text=label, variable=self.v_mode, value=key,
                           command=self.save, bg=th.CARD, fg=th.INK,
                           activebackground=th.CARD, activeforeground=th.INK,
                           selectcolor=th.FIELD, font=F["cute"], bd=0,
                           highlightthickness=0, anchor="w").pack(anchor="w")
        self.lbl_mode = tk.Label(c, text="", bg=th.CARD, fg=th.INK_SUB,
                                 font=F["small"], anchor="w", justify="left",
                                 wraplength=760)
        self.lbl_mode.pack(fill="x", pady=(2, 0))

        for v in (self.v_interval, self.v_times, self.v_gap, self.v_target):
            v.trace_add("write", lambda *a: self.save())
        self.update_view()

    MODE_HELP = {
        "foreground": "いちばん確実ですが、ARKを見ていないあいだは送られません。",
        "swap": "ARKを一瞬だけ前に出して送り、すぐ元の窓に戻します。裏で作業していても"
                "効きますが、そのあいだ画面が一瞬ちらつきます。"
                "文字を打っている最中に来ると、そのキーがARKに入ることがあります。",
        "post": "ARKのウィンドウにキーの信号を直接投げます。ちらつかず裏のままですが、"
                "ゲームによっては完全に無視されます。「▶ ためす」で効くか確かめてください。",
        "always": "⚠ 前面が何であろうと送ります。メモ帳やブラウザに文字が入ります。",
    }

    # ---------------- 設定の読み書き ----------------
    def _int(self, var, default, lo, hi):
        try:
            return max(lo, min(hi, int(float(var.get()))))
        except ValueError:
            return default

    def key_name(self):
        label = self.v_key.get()
        for k, lbl in afk.key_choices():
            if lbl == label:
                return k
        return afk.DEFAULT_KEY

    def save(self):
        c = self.app.cfg
        c["afk_key"] = self.key_name()
        c["afk_interval"] = self._int(self.v_interval, 120, 5, 3600)
        c["afk_times"] = self._int(self.v_times, 1, 1, 20)
        c["afk_gap_ms"] = self._int(self.v_gap, 60, 10, 2000)
        c["afk_target"] = self.v_target.get().strip()
        c["afk_mode"] = self.v_mode.get()
        self.update_view()

    def pick_foreground(self):
        """このボタンを押した瞬間は自分が最前面なので、少し待ってから調べる。"""
        self.app.after(1500, self._pick_now)
        self.lbl_sub.config(
            text="1.5秒以内に対象のウィンドウをクリックしてください…")

    def _pick_now(self):
        name = afk.foreground_exe()
        if name and name.lower() != "arkbreedingtimer.exe":
            self.v_target.set(name)
        self.update_view()

    def test_once(self):
        """いまのモードで1回送ってみる。効くかどうかはARK側を見て確かめる。"""
        self.save()
        mode = self.v_mode.get()
        times = self._int(self.v_times, 1, 1, 20)
        gap = self._int(self.v_gap, 60, 10, 2000)
        target = self.v_target.get().strip()
        if mode == "foreground":
            # 今このアプリを触っているので、そのままだと必ず失敗する。
            # 少し待ってから、対象に切り替えてもらう。
            self.lbl_sub.config(text="3秒以内に ARK をクリックして前に出してください…")
            self.app.after(3000, lambda: self._test_now(mode, target, times, gap))
            return
        self._test_now(mode, target, times, gap)

    def _test_now(self, mode, target, times, gap):
        n, why = afk.send(mode, target, self.key_name(), times, gap)
        if n:
            self.lbl_sub.config(
                text="✅ %s を %d回 送りました（ARK側で動いたか見てください）"
                     % (afk.key_label(self.key_name()), n))
        else:
            self.lbl_sub.config(text="⚠ 送れませんでした: %s" % (why or "原因不明"))

    # ---------------- 開始・停止 ----------------
    def toggle(self):
        self.app.afk_running = not self.app.afk_running
        if self.app.afk_running:
            self.save()
            self.app.afk_next = time.time() + self.app.cfg["afk_interval"]
            self.app.afk_count = 0
        self.update_view()

    def update_view(self, now=None):
        now = now or time.time()
        cfg = self.app.cfg
        on = self.app.afk_running
        mode = cfg.get("afk_mode") or afk.DEFAULT_MODE
        target = cfg.get("afk_target") or ""
        self.btn.set_text("■ とめる" if on else "▶ はじめる")
        self.lbl_mode.config(text=self.MODE_HELP.get(mode, ""),
                             fg=th.PINK_DK if mode == "always" else th.INK_SUB)

        # 対象のウィンドウが見つかっているか（swap / post のときだけ意味がある）
        if mode in ("swap", "post") and target:
            found = afk.find_window_cached(target)
            self.lbl_found.config(
                text="  ✅ 見つかっています" if found else "  ⚠ 見つかりません",
                fg=th.MINT if found else th.PINK_DK)
        else:
            self.lbl_found.config(text="")

        if not on:
            self.lbl_state.config(text="とまっています", fg=th.INK_SUB)
            self.lbl_sub.config(
                text="%s を %d秒ごとに送ります" % (
                    afk.key_label(cfg.get("afk_key")), cfg.get("afk_interval", 120)))
            return

        left = max(0, self.app.afk_next - now)
        if mode == "foreground" and target and not afk.matches(target):
            self.lbl_state.config(text="待機中（%s が前に出るまで）" % target,
                                  fg=th.INK_SUB)
        else:
            self.lbl_state.config(text="うごいています　つぎまで %s" % fmt_mmss(left),
                                  fg=th.MINT)
        msg = "これまで %d回 送りました　／　%s" % (
            self.app.afk_count, afk.key_label(cfg.get("afk_key")))
        if self.app.afk_why:
            msg += "　／　⚠ %s" % self.app.afk_why
        self.lbl_sub.config(text=msg)


def fmt_mmss(sec):
    sec = int(max(0, sec))
    return "%d:%02d" % (sec // 60, sec % 60)
