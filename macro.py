# -*- coding: utf-8 -*-
"""マクロ（連射）。決めた間隔でクリックやキーを送りつづける。

レベルアップの振り分けみたいな「同じ場所を何十回も押す」作業のためのもの。

  * 左 / 右 / 中クリック、または任意のキー
  * 間隔はミリ秒指定
  * 対象アプリが最前面のときだけ動かす安全装置つき（既定オン）
  * グローバルホットキー（既定 Ctrl+R）で入切

送信は afk.py と同じく SendInput。マウスは押す/離すを1組で送る。
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

import afk

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_MOUSE = 0
MOUSEEVENTF = {
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
    "middle": (0x0020, 0x0040),
}

ACTIONS = (
    ("left", "左クリック"),
    ("right", "右クリック"),
    ("middle", "中クリック"),
    ("key", "キー（下で指定）"),
)
DEFAULT_ACTION = "left"


def action_label(name):
    for k, lbl in ACTIONS:
        if k == name:
            return lbl
    return name


# ---------------------------------------------------------------- 送信
def _mouse_input(flag):
    return afk.INPUT(
        type=INPUT_MOUSE,
        u=afk._INPUTUNION(mi=afk.MOUSEINPUT(dx=0, dy=0, mouseData=0,
                                            dwFlags=flag, time=0, dwExtraInfo=0)))


def click(button="left", hold_ms=20):
    """いまカーソルがある場所でクリックする。"""
    pair = MOUSEEVENTF.get(button)
    if not pair:
        return False
    down, up = pair
    size = ctypes.sizeof(afk.INPUT)
    a, b = _mouse_input(down), _mouse_input(up)
    if user32.SendInput(1, ctypes.byref(a), size) != 1:
        return False
    if hold_ms > 0:
        _sleep(hold_ms / 1000.0)
    user32.SendInput(1, ctypes.byref(b), size)
    return True


# 拡張キー（E0 が付くもの）。矢印やInsert系、右Ctrl/Alt、テンキーEnter。
EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,
                0x2D, 0x2E, 0x2C, 0x90, 0x6F, 0x0D, 0xA3, 0xA5, 0x5B, 0x5C, 0x5D}
MAPVK_VK_TO_VSC = 0


def scancode_of(vk):
    return user32.MapVirtualKeyW(int(vk), MAPVK_VK_TO_VSC)


def press_vk(vk, scan=None, hold_ms=20):
    """仮想キーコードでキーを1回押す。スキャンコードで送る。"""
    vk = int(vk)
    if not scan:
        scan = scancode_of(vk)
    if not scan:
        return False
    ext = vk in EXTENDED_VKS
    down = afk._make(scan, ext, False)
    up = afk._make(scan, ext, True)
    size = ctypes.sizeof(afk.INPUT)
    if user32.SendInput(1, ctypes.byref(down), size) != 1:
        return False
    if hold_ms > 0:
        _sleep(hold_ms / 1000.0)
    user32.SendInput(1, ctypes.byref(up), size)
    return True


def _sleep(sec):
    # threading.Event().wait は精度がそこそこ良く、GILも離す
    threading.Event().wait(sec)


# ---------------------------------------------------------------- 連射スレッド
class Runner(threading.Thread):
    """止めるまでアクションを送りつづけるスレッド。

    設定は get_cfg() で毎回読み直すので、動かしたまま間隔を変えられる。
    """

    def __init__(self, get_cfg):
        super().__init__(daemon=True)
        self.get_cfg = get_cfg
        # 名前を _stop にすると Thread の内部メソッドを潰して join() が壊れる
        self._halt = threading.Event()
        self.count = 0
        self.waiting = False    # 対象が前に出るのを待っている
        self.finished = False   # 回数ぶん撃ち終わった

    def stop(self):
        self._halt.set()

    def run(self):
        while not self._halt.is_set():
            c = self.get_cfg()
            if c.get("only_target") and not afk.matches(c.get("target") or ""):
                self.waiting = True
                self._halt.wait(0.15)
                continue
            self.waiting = False
            act = c.get("action") or DEFAULT_ACTION
            if act == "key":
                ok = press_vk(c.get("key_vk") or 0, c.get("key_scan") or 0,
                              c.get("hold_ms", 20))
            else:
                ok = click(act, c.get("hold_ms", 20))
            if ok:
                self.count += 1
            limit = int(c.get("limit") or 0)
            if limit and self.count >= limit:
                self.finished = True
                break
            self._halt.wait(max(0.001, int(c.get("interval_ms") or 100) / 1000.0))


# ---------------------------------------------------------------- ホットキー
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MOD_NOREPEAT = 0x4000


class MSG(ctypes.Structure):
    _fields_ = (("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt_x", wintypes.LONG),
                ("pt_y", wintypes.LONG))


class Hotkey(threading.Thread):
    """グローバルホットキーを1つ登録して、押されたら callback を呼ぶ。

    RegisterHotKey はスレッドにひも付くので、このスレッドで
    メッセージを回しつづける必要がある。
    """

    def __init__(self, mods, vk, callback):
        super().__init__(daemon=True)
        self.mods = int(mods)
        self.vk = int(vk)
        self.callback = callback
        self.ready = threading.Event()
        self.ok = False
        self.error = ""
        self._tid = 0

    def run(self):
        self._tid = kernel32.GetCurrentThreadId()
        self.ok = bool(user32.RegisterHotKey(None, 1, self.mods | MOD_NOREPEAT,
                                             self.vk))
        if not self.ok:
            # だいたい「他のアプリが同じ組み合わせを押さえている」
            self.error = "他のアプリに取られているかもしれません"
        self.ready.set()
        if not self.ok:
            return
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    self.callback()
                except Exception:
                    pass
        user32.UnregisterHotKey(None, 1)

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)


# ---------------------------------------------------------------- キーの名前
VK_NAMES = {
    0x08: "BackSpace", 0x09: "Tab", 0x0D: "Enter", 0x10: "Shift", 0x11: "Ctrl",
    0x12: "Alt", 0x14: "CapsLock", 0x1B: "Esc", 0x20: "Space", 0x21: "PageUp",
    0x22: "PageDown", 0x23: "End", 0x24: "Home", 0x25: "←", 0x26: "↑",
    0x27: "→", 0x28: "↓", 0x2D: "Insert", 0x2E: "Delete",
    0xA0: "左Shift", 0xA1: "右Shift", 0xA2: "左Ctrl", 0xA3: "右Ctrl",
    0xA4: "左Alt", 0xA5: "右Alt",
}
for _i in range(1, 25):
    VK_NAMES[0x6F + _i] = "F%d" % _i


def vk_name(vk):
    vk = int(vk or 0)
    if not vk:
        return "（未設定）"
    if vk in VK_NAMES:
        return VK_NAMES[vk]
    if 0x30 <= vk <= 0x5A:      # 0-9 A-Z
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return "テンキー%d" % (vk - 0x60)
    return "キー(0x%02X)" % vk


def hotkey_name(mods, vk):
    parts = []
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_WIN:
        parts.append("Win")
    parts.append(vk_name(vk))
    return "+".join(parts)
