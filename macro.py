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

# 連射の出しかた。設定で選ぶものではなく、どちらもいつでも使える。
#   hold   … 左クリックを押しているあいだだけ送る（Ctrl+R）
#   always … 入れたらずっと送りつづける（Ctrl+T）
# 撃つ中身（なにを・何ミリ秒ごとに）は共通。出しかたが違うだけ。
MODES = (
    ("hold", "押しっぱなしで連打"),
    ("always", "ずっと連射"),
)
DEFAULT_MODE = "hold"


def mode_label(name):
    for k, lbl in MODES:
        if k == name:
            return lbl
    return name


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
# ------------------------------------------------------- ウィンドウ直送り
# 最前面でなくても届くが、生入力(RawInput/DirectInput)しか見ないゲームには
# 効かない。ARK のような UE 系は効かないことが多いので、UIの「ためす」で
# 確かめてから使うこと。効かなければ swap（一瞬だけ前に出す）を使う。
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_MOUSEMOVE = 0x0200
MK_LBUTTON, MK_RBUTTON, MK_MBUTTON = 0x0001, 0x0002, 0x0010

POST_BUTTON = {
    "left": (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON),
    "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON),
    "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON),
}

SEND_MODES = (
    ("input", "ふつうに送る（最前面のアプリに届きます）"),
    ("post", "ウィンドウに直接送る（裏でもOK・効かないゲームもある）"),
    ("swap", "一瞬だけ前に出して送り、すぐ戻す（たいてい効く・ちらつく）"),
)
DEFAULT_SEND_MODE = "input"


def send_mode_label(mode):
    for k, lbl in SEND_MODES:
        if k == mode:
            return lbl
    return mode


def _cursor_in_client(hwnd):
    """いまのマウス位置を、そのウィンドウの中の座標に直す。

    座標を渡さないとゲームが左上(0,0)を押したと解釈することがあるので、
    実際にカーソルがある所を渡す。窓の外なら真ん中にしておく。
    """
    pt = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return 0, 0
    if not user32.ScreenToClient(hwnd, ctypes.byref(pt)):
        return 0, 0
    rect = wintypes.RECT()
    if user32.GetClientRect(hwnd, ctypes.byref(rect)):
        if not (0 <= pt.x <= rect.right and 0 <= pt.y <= rect.bottom):
            return rect.right // 2, rect.bottom // 2
    return pt.x, pt.y


def post_click(hwnd, button="left", hold_ms=20):
    """ウィンドウにマウスのメッセージを直接投げる。"""
    got = POST_BUTTON.get(button)
    if not got or not hwnd:
        return False
    down_msg, up_msg, mk = got
    x, y = _cursor_in_client(hwnd)
    lp = (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
    if not user32.PostMessageW(hwnd, down_msg, mk, lp):
        return False
    _sleep(max(0.0, hold_ms / 1000.0))
    user32.PostMessageW(hwnd, up_msg, 0, lp)
    return True


def post_vk(hwnd, vk, scan=None, hold_ms=20):
    """ウィンドウにキーのメッセージを直接投げる。"""
    if not hwnd or not vk:
        return False
    if not scan:
        scan = scancode_of(vk)
    down = 1 | ((scan or 0) << 16)
    up = down | (1 << 30) | (1 << 31)
    if not user32.PostMessageW(hwnd, afk.WM_KEYDOWN, int(vk), down):
        return False
    _sleep(max(0.0, hold_ms / 1000.0))
    user32.PostMessageW(hwnd, afk.WM_KEYUP, int(vk), up)
    return True


def send_once(cfg, hwnd=None):
    """設定どおりに1回送る。(送れたか, 説明) を返す。"""
    mode = cfg.get("send_mode") or DEFAULT_SEND_MODE
    act = cfg.get("action") or DEFAULT_ACTION
    vk, scan = cfg.get("key_vk") or 0, cfg.get("key_scan") or 0
    hold = cfg.get("hold_ms", 20)
    if act == "key" and not vk:
        return False, "さきに送るキーを決めてください"

    if mode == "input":
        ok = press_vk(vk, scan, hold) if act == "key" else click(act, hold)
        return bool(ok), ""

    if hwnd is None:
        hwnd = afk.find_window(cfg.get("target") or "")
    if not hwnd:
        return False, "%s のウィンドウが見つかりません" % (cfg.get("target")
                                                          or "対象")
    if mode == "post":
        ok = (post_vk(hwnd, vk, scan, hold) if act == "key"
              else post_click(hwnd, act, hold))
        return bool(ok), ""
    if mode == "swap":
        prev = user32.GetForegroundWindow()
        if not afk._force_foreground(hwnd):
            return False, "前に出せませんでした"
        _sleep(0.12)
        ok = press_vk(vk, scan, hold) if act == "key" else click(act, hold)
        _sleep(0.04)
        if prev and prev != hwnd:
            afk._force_foreground(prev)
        return bool(ok), ""
    return False, "知らない送り方です: %s" % mode


class Runner(threading.Thread):
    """止めるまでアクションを送りつづけるスレッド。

    設定は get_cfg() で毎回読み直すので、動かしたまま間隔を変えられる。
    """

    def __init__(self, get_cfg, gate=None):
        super().__init__(daemon=True)
        self.get_cfg = get_cfg
        # gate を渡すと、それが True を返しているあいだだけ撃つ。
        # 「左クリックを押しているあいだだけ連打」はこれで作る。
        self.gate = gate
        # 名前を _stop にすると Thread の内部メソッドを潰して join() が壊れる
        self._halt = threading.Event()
        self.count = 0
        self.waiting = False    # 対象が前に出るのを待っている
        self.holding = False    # 門が開いている＝いま撃っている
        self.finished = False   # 回数ぶん撃ち終わった

    def stop(self):
        self._halt.set()

    def run(self):
        while not self._halt.is_set():
            c = self.get_cfg()
            if self.gate is not None and not self.gate():
                # 指を離しているあいだ。すぐ拾えるように短く見に行く
                self.holding = False
                self._halt.wait(0.01)
                continue
            self.holding = True
            if c.get("only_target") and not afk.matches(c.get("target") or ""):
                self.waiting = True
                self._halt.wait(0.15)
                continue
            self.waiting = False
            hwnd = None
            if (c.get("send_mode") or DEFAULT_SEND_MODE) != "input":
                hwnd = afk.find_window_cached(c.get("target") or "")
                if not hwnd:
                    self.waiting = True     # 窓が出るまで待つ
                    self._halt.wait(0.5)
                    continue
            ok, _why = send_once(c, hwnd)
            if ok:
                self.count += 1
            limit = int(c.get("limit") or 0)
            if limit and self.count >= limit:
                self.finished = True
                break
            self._halt.wait(max(0.001, int(c.get("interval_ms") or 100) / 1000.0))


# ------------------------------------------------- たまごマクロ（孵化器）
# 「たまごを押す → 壊す/孵す を押す」の2回だけ。壊すと次のたまごが
# 同じ場所へ繰り上がるので、同じ2か所を押しつづければ全部さばける。
# 押す場所は画面の大きさやUIの倍率で人それぞれなので、
# **1回やって見せてもらって覚える**（ClickRecorder）。
MAX_EGGS = 10        # 孵化器のたまご枠はこれだけ
VK_LBUTTON = 0x01


def cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


class ClickRecorder(threading.Thread):
    """左クリックを want 回ぶん見張って、押した場所を覚える。

    フックは使わず、キーの状態を細かく見に行くだけ。取りこぼしても
    次のクリックで拾えるし、他のアプリの邪魔をしない。
    """

    def __init__(self, want=2, on_point=None):
        super().__init__(daemon=True)
        self.want = int(want)
        self.on_point = on_point
        self.points = []
        self._halt = threading.Event()
        self.done = False

    def stop(self):
        self._halt.set()

    def run(self):
        # 「おぼえる」を押したクリック自体を拾わないよう、指が離れるまで待つ
        while not self._halt.is_set():
            if not (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
                break
            self._halt.wait(0.02)
        was_down = False
        while not self._halt.is_set() and len(self.points) < self.want:
            down = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
            if down and not was_down:
                p = cursor_pos()
                self.points.append(p)
                if self.on_point:
                    try:
                        self.on_point(len(self.points), p)
                    except Exception:
                        pass
            was_down = down
            self._halt.wait(0.015)
        self.done = True


class EggRunner(threading.Thread):
    """覚えた2か所を、たまごの数だけくり返し押す。"""

    def __init__(self, get_cfg):
        super().__init__(daemon=True)
        self.get_cfg = get_cfg
        self._halt = threading.Event()
        self.count = 0
        self.waiting = False
        self.finished = False

    def stop(self):
        self._halt.set()

    def _click_at(self, pos, cfg, hwnd):
        if not pos:
            return False
        user32.SetCursorPos(int(pos[0]), int(pos[1]))
        _sleep(0.02)
        c = dict(cfg)
        c["action"] = "left"
        ok, _why = send_once(c, hwnd)
        return ok

    def run(self):
        c = self.get_cfg()
        egg, act = c.get("egg_pos"), c.get("act_pos")
        slots = max(1, min(MAX_EGGS, int(c.get("slots") or MAX_EGGS)))
        if not egg or not act:
            self.finished = True
            return
        hwnd = None
        while not self._halt.is_set() and self.count < slots:
            if (c.get("send_mode") or DEFAULT_SEND_MODE) != "input":
                hwnd = afk.find_window_cached(c.get("target") or "")
                if not hwnd:
                    self.waiting = True
                    self._halt.wait(0.5)
                    continue
            elif c.get("only_target") and not afk.matches(c.get("target") or ""):
                self.waiting = True
                self._halt.wait(0.15)
                continue
            self.waiting = False
            self._click_at(egg, c, hwnd)
            self._halt.wait(max(0.0, int(c.get("mid_ms") or 150) / 1000.0))
            if self._halt.is_set():
                break
            self._click_at(act, c, hwnd)
            self.count += 1
            if self.count >= slots:
                break
            self._halt.wait(max(0.0, int(c.get("gap_ms") or 300) / 1000.0))
        self.finished = True


# ------------------------------------------------- 右クリックで止める
# 押されたら止めたいだけなので、フックは**覗くだけ**にして必ず次へ流す
# （右クリックそのものはゲームにちゃんと届く）。
#
# 大事なのは「自分が送った右クリックでは止まらない」こと。
# 右クリック連射をしているときに自分で自分を止めてしまうと使い物にならない。
# 低レベルフックなら注入された入力に印(LLMHF_INJECTED)が付くので、それで分ける。
WH_MOUSE_LL = 14
WM_LBUTTONDOWN_LL = 0x0201
WM_LBUTTONUP_LL = 0x0202
WM_RBUTTONDOWN_LL = 0x0204
WM_RBUTTONUP_LL = 0x0205
LLMHF_INJECTED = 0x00000001
ULONG_PTR = wintypes.WPARAM


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = (("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR))


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM,
                              ctypes.POINTER(MSLLHOOKSTRUCT))


class CancelWatch(threading.Thread):
    """本物の右クリックを見張って、押されたら callback を呼ぶ。

    callback はフックの中から呼ばれるので、**すぐ返ること**。
    （旗を立てるだけにして、画面はあとから見に行く）

    guard を渡すと、それが True を返したときだけ呼ぶ。ゲームが最前面の
    ときだけ効かせて、ほかの作業中の右クリックで止めないために使う。
    """

    def __init__(self, callback, button="right", guard=None):
        super().__init__(daemon=True)
        self.callback = callback
        self.guard = guard
        self.button = button
        self.msg = (WM_LBUTTONDOWN_LL if button == "left"
                    else WM_RBUTTONDOWN_LL)
        self._tid = 0
        self._hook = None
        self._proc = None          # GCで消えると落ちるので持っておく
        self.ready = threading.Event()
        self.ok = False

    def _on_event(self, code, wparam, lparam):
        try:
            if (code >= 0 and wparam == self.msg
                    and not (lparam.contents.flags & LLMHF_INJECTED)
                    and (self.guard is None or self.guard())):
                self.callback()
        except Exception:
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def run(self):
        self._tid = kernel32.GetCurrentThreadId()
        self._proc = HOOKPROC(self._on_event)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        self.ok = bool(self._hook)
        self.ready.set()
        if not self.ok:
            return
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)


class HoldWatch(threading.Thread):
    """ボタンを押しているあいだ held を立てておく。

    GetAsyncKeyState では駄目で、フックでないといけない。自分が送った
    クリックも「押された」に見えてしまい、指を離しても連打が止まらなくなる。
    低レベルフックなら注入された入力に印が付くので、本物だけを数えられる。

    guard を渡すと、それが True のときに押した場合だけ立てる。ゲームを
    見ているときだけ連打させるために使う。
    """

    def __init__(self, button="left", guard=None):
        super().__init__(daemon=True)
        self.button = button
        self.guard = guard
        self.down = (WM_LBUTTONDOWN_LL if button == "left"
                     else WM_RBUTTONDOWN_LL)
        self.up = WM_LBUTTONUP_LL if button == "left" else WM_RBUTTONUP_LL
        self.held = False
        self._tid = 0
        self._hook = None
        self._proc = None          # GCで消えると落ちるので持っておく
        self.ready = threading.Event()
        self.ok = False

    def _on_event(self, code, wparam, lparam):
        try:
            if code >= 0 and not (lparam.contents.flags & LLMHF_INJECTED):
                if wparam == self.down:
                    self.held = bool(self.guard is None or self.guard())
                elif wparam == self.up:
                    self.held = False
        except Exception:
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def run(self):
        self._tid = kernel32.GetCurrentThreadId()
        self._proc = HOOKPROC(self._on_event)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        self.ok = bool(self._hook)
        self.ready.set()
        if not self.ok:
            return
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    def stop(self):
        self.held = False
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)


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

    def __init__(self, mods, vk, callback, hk_id=1):
        super().__init__(daemon=True)
        self.mods = int(mods)
        self.vk = int(vk)
        self.hk_id = int(hk_id)
        self.callback = callback
        self.ready = threading.Event()
        self.ok = False
        self.error = ""
        self._tid = 0

    def run(self):
        self._tid = kernel32.GetCurrentThreadId()
        self.ok = bool(user32.RegisterHotKey(None, self.hk_id,
                                             self.mods | MOD_NOREPEAT, self.vk))
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
        user32.UnregisterHotKey(None, self.hk_id)

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


VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C


def mods_now():
    """いま押さえている修飾キー。RegisterHotKey に渡す形で返す。

    tkinter の event.state は当てにしない。Windows では NumLock が
    0x0008 に乗ってくるので、それを Alt と読み違えて勝手に Alt が
    入ってしまう（CapsLock も 0x0002 に乗る）。実際のキーの状態を見る。
    """
    m = 0
    if user32.GetAsyncKeyState(VK_CONTROL) & 0x8000:
        m |= MOD_CONTROL
    if user32.GetAsyncKeyState(VK_SHIFT) & 0x8000:
        m |= MOD_SHIFT
    if user32.GetAsyncKeyState(VK_MENU) & 0x8000:
        m |= MOD_ALT
    if (user32.GetAsyncKeyState(VK_LWIN) & 0x8000
            or user32.GetAsyncKeyState(VK_RWIN) & 0x8000):
        m |= MOD_WIN
    return m


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
