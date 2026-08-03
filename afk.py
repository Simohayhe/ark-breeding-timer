# -*- coding: utf-8 -*-
"""AFK（放置）でキックされないように、たまにキーを送る。

Windows の SendInput をスキャンコードで叩く。ゲーム（UE系）は生の入力を
見ているので、仮想キーコードではなくスキャンコードで送らないと届かない。

安全のため、既定では「対象のアプリが最前面のときだけ」送る。これを切ると
メモ帳やブラウザに勝手に文字が入るので注意。
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


# 表示名 -> (スキャンコード, 拡張キーか)
#   スキャンコードは PS/2 セット1。拡張キー(矢印など)は E0 が付くので True。
KEYS = {
    "space": ("スペース（ジャンプ）", 0x39, False),
    "w": ("W（前に少し）", 0x11, False),
    "a": ("A（左に少し）", 0x1E, False),
    "s": ("S（後ろに少し）", 0x1F, False),
    "d": ("D（右に少し）", 0x20, False),
    "left": ("← 左を向く", 0x4B, True),
    "right": ("→ 右を向く", 0x4D, True),
    "shift": ("左Shift", 0x2A, False),
    "ctrl": ("左Ctrl（しゃがみ）", 0x1D, False),
    "tab": ("Tab", 0x0F, False),
    "1": ("1（ホットバー1）", 0x02, False),
}
DEFAULT_KEY = "space"


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
    _label, scan, ext = got
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
