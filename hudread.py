# -*- coding: utf-8 -*-
"""ARKの左上を写して、ゲーム内時刻を読み取る。

左上のHUDはこう出ている（Hキーで出る表示）:

    Day: 2894
    プレイヤー - Lv 125 (トライブ: Simon)
    15:49
    アストレオス, 26°(C)

3行目の HH:MM が知りたい時刻。Day も一緒に読めるのでおまけで返す。

文字を読むのは **Windows に最初から入っている OCR**（Windows.Media.Ocr）。
追加のインストールが要らないのが利点。呼び出しは PowerShell 経由。
Python から WinRT を直接触るには外部ライブラリが要るので、そこだけ任せる。

OCR は「05 : 53」のように区切りの前後へ空白を入れてくるので、
読んだあとに詰めてから拾う。
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import tempfile
import threading
import time

# 既定で写す場所（ウィンドウの左上からの割合）。人によってUIの倍率が違うので
# 広めに取っておき、画面から調整できるようにする。
DEFAULT_RECT = (0.0, 0.0, 0.30, 0.14)

_PS = r'''
param([string]$Out, [int]$L, [int]$T, [int]$W, [int]$H, [int]$Scale,
      [int]$Thr = 225, [string]$Src = "")
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Runtime.WindowsRuntime

# --- 画面から切り出して、読みやすいように拡大＆白黒にする ---
# （$Src を渡すと、画面ではなくその画像を読む。動きを確かめる用）
if ($Src) {
  $bmp = New-Object System.Drawing.Bitmap ([System.Drawing.Image]::FromFile($Src))
  $W = $bmp.Width; $H = $bmp.Height
} else {
  $bmp = New-Object System.Drawing.Bitmap $W, $H
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($L, $T, 0, 0, (New-Object System.Drawing.Size $W, $H))
  $g.Dispose()
}
$bw = New-Object System.Drawing.Bitmap ($W * $Scale), ($H * $Scale)
$g2 = [System.Drawing.Graphics]::FromImage($bw)
$g2.InterpolationMode = "HighQualityBicubic"
$g2.DrawImage($bmp, 0, 0, ($W * $Scale), ($H * $Scale))
$g2.Dispose()
# HUDの字は「ほぼ真っ白」。しきい値を高めに取らないと、明るい地面や
# 金属の反射まで拾ってしまい、字が埋もれて読めなくなる。
for ($y = 0; $y -lt $bw.Height; $y++) {
  for ($x = 0; $x -lt $bw.Width; $x++) {
    $c = $bw.GetPixel($x, $y)
    $v = ($c.R * 0.299 + $c.G * 0.587 + $c.B * 0.114)
    if ($v -gt $Thr) { $bw.SetPixel($x, $y, [System.Drawing.Color]::Black) }
    else { $bw.SetPixel($x, $y, [System.Drawing.Color]::White) }
  }
}
$bw.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose(); $bw.Dispose()

# --- Windows の OCR にかける ---
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $t) {
  $m = $asTask.MakeGenericMethod($t)
  $task = $m.Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result
}
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Out)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$sb = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) { Write-Output "<<NOENGINE>>"; exit }
$res = Await ($engine.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
foreach ($line in $res.Lines) { Write-Output $line.Text }
'''


class HudError(Exception):
    pass


def _ps_path():
    """毎回書き出さずに済むよう、同じ場所へ置いておく。"""
    path = os.path.join(tempfile.gettempdir(), "meridian_hud_ocr.ps1")
    if not os.path.exists(path):
        with io.open(path, "w", encoding="utf-8-sig") as f:
            f.write(_PS)
    return path


def capture_text(rect, scale=3, timeout=25, src="", thr=225):
    """画面の (左, 上, 幅, 高さ) を写して、読めた行を返す。

    src に画像のパスを渡すと、画面ではなくその画像を読む（確認用）。
    """
    left, top, w, h = (int(v) for v in rect)
    if not src and (w < 20 or h < 10):
        raise HudError("写す範囲が小さすぎます")
    out = os.path.join(tempfile.gettempdir(), "meridian_hud.png")
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", _ps_path(), "-Out", out, "-L", str(left), "-T", str(top),
           "-W", str(w), "-H", str(h), "-Scale", str(scale),
           "-Thr", str(thr)]
    if src:
        cmd += ["-Src", src]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess,
                                                 "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise HudError("読み取りに時間がかかりすぎました")
    text = (p.stdout or b"").decode("utf-8", "replace")
    if "<<NOENGINE>>" in text:
        raise HudError("この Windows では文字認識が使えません")
    if p.returncode != 0 and not text.strip():
        err = (p.stderr or b"").decode("utf-8", "replace").strip()
        raise HudError(err[:120] or "読み取りに失敗しました")
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


# OCR は「05 : 53」のように空白を入れてくる。詰めてから探す。
_TIME = re.compile(r"([0-2]?\d)[:：;.](\d{2})")
_DAY = re.compile(r"Day[^0-9]{0,4}(\d{1,6})", re.I)


def parse(lines):
    """読めた行から (ゲーム内秒, Day, マップ名) を拾う。

    マップ名は「アストレオス, 26°(C)」の行から。どのマップにいるかが
    分かれば、その時計へ合わせられる。
    """
    joined = "\n".join(lines)
    flat = re.sub(r"[ 　]", "", joined)
    day = None
    m = _DAY.search(flat)
    if m:
        day = int(m.group(1))
    sec = None
    for hh, mm in _TIME.findall(flat):
        h, mi = int(hh), int(mm)
        if 0 <= h < 24 and 0 <= mi < 60:
            sec = h * 3600 + mi * 60
            break                     # HUDでは時刻が先に出てくる
    # 最後の行にマップ名と気温が出る。「, 26°(C)」の手前を拾う
    where = ""
    for ln in reversed(lines):
        flat_ln = re.sub(r"[ 　]", "", ln)
        m2 = re.match(r"^(.{2,20}?)[,、.]\s*[-−]?\d{1,3}", flat_ln)
        if m2:
            where = m2.group(1)
            break
    return sec, day, where


# 明るさのしきい値と拡大率の組み合わせ。背景やUIの倍率で当たり外れが
# あるので、うまくいくまで順に試す。効いた組はあとで最初に回す。
TRY_SETTINGS = ((200, 3), (225, 4), (180, 3), (210, 4), (160, 2), (240, 4))


def read_once(rect, prefer=None, src=""):
    """1回読む。(ゲーム内秒, Day, マップ名, 読めた行, 効いた設定) を返す。

    prefer に前回うまくいった (しきい値, 拡大) を渡すと、そこから試す。
    """
    order = list(TRY_SETTINGS)
    if prefer and tuple(prefer) in order:
        order.remove(tuple(prefer))
        order.insert(0, tuple(prefer))
    last = []
    for thr, scale in order:
        lines = capture_text(rect, scale=scale, thr=thr, src=src)
        sec, day, where = parse(lines)
        last = lines or last
        if sec is not None:
            return sec, day, where, lines, (thr, scale)
    return None, None, "", last, None


def read_steady(rect, tries=3, gap=2.0, prefer=None):
    """何回か読んで、辻褄が合ったときだけ採用する。

    1回の読み違いで時計を壊さないための用心。時刻は前へ進むはずなので、
    2回目以降が「同じか、少しだけ先」でなければ捨てる。
    戻り値 (ゲーム内秒, Day, 説明)。読めなければ最初が None。
    """
    seen = []
    lines_last = []
    used = prefer
    for i in range(max(1, int(tries))):
        if i:
            time.sleep(gap)
        try:
            sec, day, where, lines, got = read_once(rect, prefer=used)
        except HudError as e:
            return None, None, None, str(e)
        lines_last = lines
        if got:
            used = got            # 効いた設定は次から最初に試す
        if sec is None:
            continue
        seen.append((sec, day, where))
    if not seen:
        return None, None, None, ("時刻が見つかりません（読めた文字: %s）"
                                  % (" / ".join(lines_last)[:80]
                                     or "何も読めません"))
    if len(seen) == 1:
        return seen[0][0], seen[0][1], seen[0][2], "1回だけ読めました"
    # 進み方が変でないか。1日ぶんで折り返す
    ok = True
    for (a, _d1, _w1), (b, _d2, _w2) in zip(seen, seen[1:]):
        fwd = (b - a) % 86400
        if fwd > 3600:          # 数十秒のはずが1時間以上進んだ＝読み違い
            ok = False
    if not ok:
        return None, None, None, ("読み取りがぶれています（%s）"
                                  % "→".join("%02d:%02d"
                                             % (s // 3600, s % 3600 // 60)
                                             for s, _d, _w in seen))
    sec, day, where = seen[-1]
    return sec, day, where, "%d回読んで一致しました" % len(seen)


class AutoReader(threading.Thread):
    """言われた間隔で画面を読む係。

    ずっと回すと重いので、動くのは「入」のあいだだけ。読めた・読めなかったを
    on_result(秒, Day, マップ名, 説明) で知らせる。Tk は触らないので、
    受け取った側が本体の周期処理で反映すること。
    """

    def __init__(self, get_cfg, on_result, find_window):
        super().__init__(daemon=True)
        self.get_cfg = get_cfg      # {"on":.., "minutes":.., "rect":.., "prefer":..}
        self.on_result = on_result
        self.find_window = find_window
        self._halt = threading.Event()
        self._wake = threading.Event()
        self.next_at = 0.0

    def stop(self):
        self._halt.set()
        self._wake.set()

    def poke(self):
        """すぐ1回読ませる（「はじめる」を押したとき用）。"""
        self.next_at = 0.0
        self._wake.set()

    def run(self):
        while not self._halt.is_set():
            c = self.get_cfg() or {}
            if not c.get("on"):
                self.next_at = 0.0
                self._wake.wait(3.0)
                self._wake.clear()
                continue
            now = time.time()
            if now < self.next_at:
                self._wake.wait(min(20.0, self.next_at - now))
                self._wake.clear()
                continue
            self.next_at = now + max(60.0, float(c.get("minutes") or 10) * 60)
            hwnd = self.find_window()
            if not hwnd:
                self.on_result(None, None, None, "ARKが起動していません")
                continue
            try:
                rect = rect_from_window(hwnd, c.get("rect") or DEFAULT_RECT)
                pref = c.get("prefer")
                sec, day, where, why = read_steady(
                    rect, tries=2, gap=1.5,
                    prefer=tuple(pref) if pref else None)
            except HudError as e:
                self.on_result(None, None, None, str(e))
                continue
            self.on_result(sec, day, where, why)


def rect_from_window(hwnd, fracs):
    """ウィンドウの中の割合 (x, y, w, h) を、画面の座標に直す。"""
    import ctypes
    from ctypes import wintypes
    r = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r)):
        raise HudError("ウィンドウの場所が分かりません")
    W, H = r.right - r.left, r.bottom - r.top
    fx, fy, fw, fh = fracs
    return (int(r.left + W * fx), int(r.top + H * fy),
            max(20, int(W * fw)), max(10, int(H * fh)))
