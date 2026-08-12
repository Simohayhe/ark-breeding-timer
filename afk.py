# -*- coding: utf-8 -*-
"""AFK（放置）でキックされないように、たまにキーを送る。

送り方が3通りある。どれが効くかはゲームの作りによるので、UIの「ためす」で
確かめてから使うこと。

  foreground : 対象が最前面のときだけ SendInput する（安全・確実だが裏では送れない）
  post       : ウィンドウに WM_KEYDOWN/UP を直接投げる（裏でも送れるが、
               生入力(RawInput/DirectInput)しか見ないゲームには届かない）
  swap       : 一瞬だけ対象を前に出して SendInput し、すぐ元の窓に戻す
               （たいてい効くが画面が一瞬ちらつく）
  always     : 前面が何であろうと SendInput する（他のアプリに文字が入る）

SendInput は仮想キーコードではなくスキャンコードで送る。ゲーム（UE系）は
生の入力を見ているので、そうしないと届かないことがある。
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

ULONG_PTR = wintypes.WPARAM


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR))


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR))


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD))


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


# 表示名 -> (表示名, スキャンコード, 拡張キーか, 仮想キーコード)
#   スキャンコードは PS/2 セット1。拡張キー(矢印など)は E0 が付くので True。
#   仮想キーコードは post モード（WM_KEYDOWN）で使う。
KEYS = {
    "space": ("スペース（ジャンプ）", 0x39, False, 0x20),
    "w": ("W（前に少し）", 0x11, False, 0x57),
    "a": ("A（左に少し）", 0x1E, False, 0x41),
    "s": ("S（後ろに少し）", 0x1F, False, 0x53),
    "d": ("D（右に少し）", 0x20, False, 0x44),
    "left": ("← 左を向く", 0x4B, True, 0x25),
    "right": ("→ 右を向く", 0x4D, True, 0x27),
    "shift": ("左Shift", 0x2A, False, 0xA0),
    "ctrl": ("左Ctrl（しゃがみ）", 0x1D, False, 0xA2),
    "tab": ("Tab", 0x0F, False, 0x09),
    "1": ("1（ホットバー1）", 0x02, False, 0x31),
}
DEFAULT_KEY = "space"

MODES = (
    ("foreground", "ARKが最前面のときだけ送る（安全・確実）"),
    ("swap", "一瞬だけ前に出して、すぐ元に戻す（裏でもOK・ちらつく）"),
    ("post", "ウィンドウに直接送る（裏でもOK・効かないゲームもある）"),
    ("always", "前面が何でも送る（他のアプリに文字が入ります）"),
)
DEFAULT_MODE = "foreground"


def mode_label(mode):
    for k, lbl in MODES:
        if k == mode:
            return lbl
    return mode


def key_choices():
    """[(値, 表示名), ...]"""
    return [(k, v[0]) for k, v in KEYS.items()]


def key_label(name):
    got = KEYS.get(name)
    return got[0] if got else name


def _make(scan, extended, up):
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    if up:
        flags |= KEYEVENTF_KEYUP
    return INPUT(type=INPUT_KEYBOARD,
                 u=_INPUTUNION(ki=KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags,
                                             time=0, dwExtraInfo=0)))


def tap(name, hold_ms=40):
    """キーを1回、短く押して離す。送れたら True。"""
    got = KEYS.get(name)
    if not got:
        return False
    _label, scan, ext, _vk = got
    down = _make(scan, ext, False)
    up = _make(scan, ext, True)
    n = user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    if n != 1:
        return False
    time.sleep(max(0.0, hold_ms / 1000.0))
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
    return True


def burst(name, times=1, gap_ms=60, hold_ms=40):
    """連打する。送れた回数を返す。"""
    sent = 0
    for i in range(max(1, int(times))):
        if not tap(name, hold_ms):
            break
        sent += 1
        if i + 1 < times:
            time.sleep(max(0.0, gap_ms / 1000.0))
    return sent


def foreground_exe():
    """いま最前面のウィンドウの exe 名（例 'ArkAscended.exe'）。"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(h)
    return ""


def foreground_title():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def matches(target):
    """対象アプリが最前面か。target が空なら常に True。"""
    if not target:
        return True
    cur = foreground_exe().lower()
    return cur == target.strip().lower()


# ------------------------------------------------------------ ウィンドウ探し
_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _exe_of_hwnd(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(h)
    return ""


def find_window(target):
    """exe名から、そのアプリの表に出ているウィンドウを1つ探す。"""
    if not target:
        return 0
    want = target.strip().lower()
    found = []

    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        if _exe_of_hwnd(hwnd).lower() == want:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(_EnumProc(cb), 0)
    return found[0] if found else 0


_win_cache = {}


def find_window_cached(target, ttl=1.0):
    """画面の表示用。毎回の全ウィンドウ走査は重いので少しキャッシュする。"""
    now = time.time()
    hit = _win_cache.get(target)
    if hit and now - hit[0] < ttl:
        return hit[1]
    hwnd = find_window(target)
    _win_cache[target] = (now, hwnd)
    return hwnd


# ------------------------------------------------------------ post モード
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101


def post_key(hwnd, name, hold_ms=40):
    """ウィンドウに WM_KEYDOWN/UP を直接投げる（最前面でなくても届く）。

    ただし RawInput / DirectInput しか見ないゲームには効かない。
    """
    got = KEYS.get(name)
    if not got or not hwnd:
        return False
    _label, scan, ext, vk = got
    ext_bit = 1 << 24 if ext else 0
    down = 1 | (scan << 16) | ext_bit
    up = down | (1 << 30) | (1 << 31)
    if not user32.PostMessageW(hwnd, WM_KEYDOWN, vk, down):
        return False
    time.sleep(max(0.0, hold_ms / 1000.0))
    user32.PostMessageW(hwnd, WM_KEYUP, vk, up)
    return True


# ------------------------------------------------------------ swap モード
SW_RESTORE = 9


def _force_foreground(hwnd):
    """他プロセスの窓を前に出す。素の SetForegroundWindow は弾かれるので、
    前面スレッドに入力キューをくっつけてから呼ぶ。"""
    if not hwnd:
        return False
    if user32.GetForegroundWindow() == hwnd:
        return True
    fg = user32.GetForegroundWindow()
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = False
    if fg_tid and fg_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    ok = bool(user32.SetForegroundWindow(hwnd))
    user32.BringWindowToTop(hwnd)
    if attached:
        user32.AttachThreadInput(cur_tid, fg_tid, False)
    return ok


def send_via_swap(hwnd, name, times=1, gap_ms=60, hold_ms=40, settle_ms=140):
    """一瞬だけ対象を前に出してキーを送り、元の窓に戻す。"""
    if not hwnd:
        return 0
    prev = user32.GetForegroundWindow()
    if not _force_foreground(hwnd):
        return 0
    time.sleep(settle_ms / 1000.0)   # 前面が切り替わるのを待つ
    sent = burst(name, times, gap_ms, hold_ms)
    time.sleep(0.05)
    if prev and prev != hwnd:
        _force_foreground(prev)
    return sent


# ------------------------------------------------------------ まとめ役
def send(mode, target, name, times=1, gap_ms=60, hold_ms=40):
    """モードに応じて送る。(送れた回数, 状況の説明) を返す。"""
    if mode == "always":
        return burst(name, times, gap_ms, hold_ms), ""
    if mode == "foreground":
        if not matches(target):
            return 0, "%s が最前面ではありません" % (target or "対象")
        return burst(name, times, gap_ms, hold_ms), ""
    hwnd = find_window(target)
    if not hwnd:
        return 0, "%s のウィンドウが見つかりません" % (target or "対象")
    if mode == "post":
        sent = 0
        for i in range(max(1, int(times))):
            if not post_key(hwnd, name, hold_ms):
                break
            sent += 1
            if i + 1 < times:
                time.sleep(max(0.0, gap_ms / 1000.0))
        return sent, ""
    if mode == "swap":
        return send_via_swap(hwnd, name, times, gap_ms, hold_ms), ""
    return 0, "知らないモードです: %s" % mode
