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
import time
from ctypes import wintypes

import afk

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_MOUSE = 0
MOUSEEVENTF = {
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
    "middle": (0x0020, 0x0040),
    # サイドボタンは押す/離すの旗が共通で、どちらのボタンかは mouseData で渡す
    "x1": (0x0080, 0x0100),
    "x2": (0x0080, 0x0100),
}
# サイドボタンの番号。1=手前（戻る）、2=奥（進む）
MOUSE_DATA = {"x1": 1, "x2": 2}

ACTIONS = (
    ("left", "左クリック"),
    ("right", "右クリック"),
    ("middle", "中クリック"),
    ("x1", "サイドボタン1（戻る）"),
    ("x2", "サイドボタン2（進む）"),
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


MAX_STEPS = 3        # 1回に続けて送れる行動の数


# ------------------------------------------------- 秒・分の読み書き
# ミリ秒で入れさせると桁を間違える。「0.5」「2秒」「1分30秒」「1:30」で書く。
_UNITS = (("ミリ秒", 0.001), ("ミリ", 0.001), ("ms", 0.001),
          ("分", 60.0), ("m", 60.0), ("秒", 1.0), ("s", 1.0))


def parse_secs(text, default=None):
    """「0.5」「2秒」「1分30秒」「1:30」を秒にする。読めなければ default。"""
    t = (text or "").strip().lower()
    if not t:
        return default
    t = t.translate(str.maketrans("０１２３４５６７８９．：",
                                  "0123456789.:"))
    if ":" in t:                       # 1:30 = 1分30秒
        got = t.split(":")
        try:
            mm, ss = float(got[0] or 0), float(got[1] or 0)
        except ValueError:
            return default
        return mm * 60.0 + ss
    total, rest, hit = 0.0, t, False
    for unit, mul in _UNITS:
        i = rest.find(unit)
        while i >= 0:
            head = rest[:i]
            num = "".join(c for c in head if c.isdigit() or c == ".")
            if num:
                try:
                    total += float(num) * mul
                    hit = True
                except ValueError:
                    pass
            rest = rest[i + len(unit):]
            i = rest.find(unit)
    if hit:
        # 「1分30」のように、最後の単位が抜けているぶんを秒として足す
        num = "".join(c for c in rest if c.isdigit() or c == ".")
        if num:
            try:
                total += float(num)
            except ValueError:
                pass
        return total
    try:
        return float(t)                # 単位なしは秒とみなす
    except ValueError:
        return default


def fmt_secs(sec):
    """秒を、書き戻せる形の文字で。"""
    try:
        sec = float(sec)
    except (TypeError, ValueError):
        return "0"
    if sec >= 60:
        m, s = int(sec // 60), sec - int(sec // 60) * 60
        if abs(s) < 0.0005:
            return "%d分" % m
        return "%d分%s秒" % (m, ("%.3f" % s).rstrip("0").rstrip("."))
    return ("%.3f" % sec).rstrip("0").rstrip(".") or "0"


def action_label(name):
    for k, lbl in ACTIONS:
        if k == name:
            return lbl
    return name


# ---------------------------------------------------------------- 送信
def _mouse_input(flag, data=0):
    return afk.INPUT(
        type=INPUT_MOUSE,
        u=afk._INPUTUNION(mi=afk.MOUSEINPUT(dx=0, dy=0, mouseData=int(data),
                                            dwFlags=flag, time=0, dwExtraInfo=0)))


def mouse_hold(button="left", down=True):
    """マウスのボタンを押しっぱなしにする／離す。"""
    pair = MOUSEEVENTF.get(button)
    if not pair:
        return False
    a = _mouse_input(pair[0] if down else pair[1], MOUSE_DATA.get(button, 0))
    return user32.SendInput(1, ctypes.byref(a), ctypes.sizeof(afk.INPUT)) == 1


def click(button="left", hold_ms=20):
    """いまカーソルがある場所でクリックする。"""
    pair = MOUSEEVENTF.get(button)
    if not pair:
        return False
    down, up = pair
    data = MOUSE_DATA.get(button, 0)
    size = ctypes.sizeof(afk.INPUT)
    a, b = _mouse_input(down, data), _mouse_input(up, data)
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


def key_hold(vk, scan=None, down=True):
    """キーを押しっぱなしにする／離す。"""
    vk = int(vk)
    if not scan:
        scan = scancode_of(vk)
    if not scan:
        return False
    a = afk._make(scan, vk in EXTENDED_VKS, not down)
    return user32.SendInput(1, ctypes.byref(a), ctypes.sizeof(afk.INPUT)) == 1


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
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C
WM_MOUSEMOVE = 0x0200
MK_LBUTTON, MK_RBUTTON, MK_MBUTTON = 0x0001, 0x0002, 0x0010
MK_XBUTTON1, MK_XBUTTON2 = 0x0020, 0x0040

# (押す, 離す, 押されている印, サイドボタンの番号)
# サイドボタンだけは wParam の上位16ビットに番号を入れる決まり
POST_BUTTON = {
    "left": (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON, 0),
    "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON, 0),
    "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON, 0),
    "x1": (WM_XBUTTONDOWN, WM_XBUTTONUP, MK_XBUTTON1, 1),
    "x2": (WM_XBUTTONDOWN, WM_XBUTTONUP, MK_XBUTTON2, 2),
}


def _wparam(mk, xb):
    """サイドボタンは上位に番号、下位に押されている印。"""
    return ((int(xb) & 0xFFFF) << 16) | (int(mk) & 0xFFFF)

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
    down_msg, up_msg, mk, xb = got
    x, y = _cursor_in_client(hwnd)
    lp = (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
    if not user32.PostMessageW(hwnd, down_msg, _wparam(mk, xb), lp):
        return False
    _sleep(max(0.0, hold_ms / 1000.0))
    user32.PostMessageW(hwnd, up_msg, _wparam(0, xb), lp)
    return True


def post_mouse_hold(hwnd, button="left", down=True):
    """ウィンドウに、押しっぱなし／離す のマウスメッセージを投げる。"""
    got = POST_BUTTON.get(button)
    if not got or not hwnd:
        return False
    down_msg, up_msg, mk, xb = got
    x, y = _cursor_in_client(hwnd)
    lp = (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)
    if down:
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, mk, lp)
        return bool(user32.PostMessageW(hwnd, down_msg, _wparam(mk, xb), lp))
    return bool(user32.PostMessageW(hwnd, up_msg, _wparam(0, xb), lp))


def post_key_hold(hwnd, vk, scan=None, down=True, again=False):
    """ウィンドウに、押しっぱなし／離す のキーメッセージを投げる。

    押しつづけているあいだ Windows は WM_KEYDOWN を繰り返し送るので、
    こちらも again=True で送り直す（30ビット目が「前も押されていた」印）。
    """
    if not hwnd or not vk:
        return False
    if not scan:
        scan = scancode_of(vk)
    lp = 1 | ((scan or 0) << 16)
    if down:
        if again:
            lp |= (1 << 30)
        return bool(user32.PostMessageW(hwnd, afk.WM_KEYDOWN, int(vk), lp))
    return bool(user32.PostMessageW(hwnd, afk.WM_KEYUP, int(vk),
                                    lp | (1 << 30) | (1 << 31)))


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


def steps_of(cfg):
    """設定から行動の並びを作る。空なら、昔ながらの1行動として読む。"""
    got = []
    for st in (cfg.get("steps") or []):
        act = (st.get("action") or "").strip()
        if not act or act == "none":
            continue
        got.append({"action": act,
                    "key_vk": st.get("key_vk") or 0,
                    "key_scan": st.get("key_scan") or 0,
                    "hold_ms": st.get("hold_ms", cfg.get("hold_ms", 20)),
                    "gap_ms": st.get("gap_ms", 120),
                    "every": max(1, int(st.get("every") or 1))})
        if len(got) >= MAX_STEPS:
            break
    if got:
        return got
    return [{"action": cfg.get("action") or DEFAULT_ACTION,
             "key_vk": cfg.get("key_vk") or 0,
             "key_scan": cfg.get("key_scan") or 0,
             "hold_ms": cfg.get("hold_ms", 20),
             "gap_ms": 0, "every": 1}]


def due(step, cycle):
    """この回に、その行動を混ぜるか。

    every=3 なら「3回に1度」。cycle=None は、ためし打ち用の全部入り。
    """
    ev = max(1, int(step.get("every") or 1))
    if ev <= 1 or cycle is None:
        return True
    return cycle % ev == 0


def send_seq(cfg, hwnd=None, halt=None, cycle=None):
    """行動の並びを、あいだを空けながら順に送る。

    cycle はこれが何回目のくり返しか。「3回に1度」の行動は、その回だけ混ぜる。
    途中で止められるように halt（Event）を見る。3行動目まで送り終える前に
    止めたいことのほうが多い。
    """
    steps = [st for st in steps_of(cfg) if due(st, cycle)]
    sent, why = 0, ""
    for i, st in enumerate(steps):
        if halt is not None and halt.is_set():
            break
        one = dict(cfg)
        one.update(st)
        ok, msg = send_once(one, hwnd)
        if ok:
            sent += 1
        elif msg:
            why = msg
        if i + 1 < len(steps):
            gap = max(0.0, float(st.get("gap_ms") or 0) / 1000.0)
            if halt is not None:
                halt.wait(gap)
            elif gap:
                _sleep(gap)
    return sent > 0, why


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
        self.cycle = 0          # 何回目のくり返しか（「3回に1度」に使う）
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
            self.cycle += 1
            ok, _why = send_seq(c, hwnd, self._halt, self.cycle)
            if ok:
                self.count += 1
            limit = int(c.get("limit") or 0)
            if limit and self.count >= limit:
                self.finished = True
                break
            # 待っているあいだも設定を見に行く。5分待ちの最中に1秒へ変えても、
            # 前の5分を待ち切らずに済む（止めて入れ直さなくていい）
            waited = 0.0
            while not self._halt.is_set():
                want = max(0.001,
                           int(self.get_cfg().get("interval_ms") or 100) / 1000.0)
                if waited >= want:
                    break
                self._halt.wait(min(0.2, want - waited))
                waited += min(0.2, want - waited)


class Holder(threading.Thread):
    """止めるまで押しっぱなしにする。

    連射とちがって、押して離してをくり返さない。押したまま置いておく。
    採取をずっと続けたいときや、走りっぱなしにしたいときのもの。

    大事なのは**必ず離すこと**。押したままスレッドが終わると、キーが
    押されっぱなしのまま残って他のアプリまで巻き添えになる。
    対象が裏に回ったときも、いったん離す。
    """

    def __init__(self, get_cfg):
        super().__init__(daemon=True)
        self.get_cfg = get_cfg
        self._halt = threading.Event()
        self.down = False          # いま押していることになっているか
        self.waiting = False       # 対象が前に出るのを待っている
        self.error = ""

    def stop(self):
        self._halt.set()

    def _send(self, c, hwnd, down, again=False):
        act = c.get("action") or DEFAULT_ACTION
        mode = c.get("send_mode") or DEFAULT_SEND_MODE
        vk, scan = c.get("key_vk") or 0, c.get("key_scan") or 0
        if mode == "post":
            if act == "key":
                return post_key_hold(hwnd, vk, scan, down, again)
            return post_mouse_hold(hwnd, act, down)
        if act == "key":
            return key_hold(vk, scan, down)
        return mouse_hold(act, down)

    def _release(self, c, hwnd):
        if self.down:
            self._send(c, hwnd, False)
            self.down = False

    def run(self):
        c, hwnd = self.get_cfg(), None
        try:
            while not self._halt.is_set():
                c = self.get_cfg()
                mode = c.get("send_mode") or DEFAULT_SEND_MODE
                if c.get("only_target") and not afk.matches(c.get("target") or ""):
                    self._release(c, hwnd)      # 裏に回ったら離しておく
                    self.waiting = True
                    self._halt.wait(0.15)
                    continue
                hwnd = None
                if mode != "input":
                    hwnd = afk.find_window_cached(c.get("target") or "")
                    if not hwnd:
                        self._release(c, hwnd)
                        self.waiting = True
                        self._halt.wait(0.5)
                        continue
                self.waiting = False
                # 押しつづけているあいだ、本物のキーは繰り返し届く。同じにする
                if self._send(c, hwnd, True, again=self.down):
                    self.down = True
                self._halt.wait(0.05)
        finally:
            self._release(c, hwnd)              # なにがあっても離す


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
        self.since = 0.0           # 押しはじめた時刻（離すと0）
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
                    self.since = time.time() if self.held else 0.0
                elif wparam == self.up:
                    self.held = False
                    self.since = 0.0
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

    def held_for(self):
        """押しつづけている秒数。離していれば 0。"""
        return (time.time() - self.since) if (self.held and self.since) else 0.0

    def stop(self):
        self.held = False
        self.since = 0.0
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
