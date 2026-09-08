# -*- coding: utf-8 -*-
"""スクショから「品名と個数」を読む。

ARK のインベントリは、1マスの中が

    x65 ←左上に個数
    （絵）
    アルゲンタ      ←名前。2行に折り返すし、長いと … で切れる
    ヴィスの鉤爪
              32.5 ←右下は重さ。個数ではない

という並び。上から行を読むだけでは、どの個数がどの名前のものか分からない。
そこで **文字の位置**をもらって、マスごとに束ねる。

さらに日本語のOCRは、かなを1文字ずつ別の語として返してくる。
マスの中で位置順につなぎ直せば元の名前に戻る。
"""
from __future__ import annotations

import difflib
import re
import statistics

import hudread

# 濃さと拡大率。上から順にためして、いちばん多く取れたものを使う。
TRIES = ((150, 2), (120, 2), (180, 2), (150, 3), (200, 2))

# 個数。「x65」「X65」「×65」。OCRが x と数字を切り離すこともある。
_QTY = re.compile(r"^[xX×✕*]\s*(\d{1,5})$")
_QTY_MARK = re.compile(r"^[xX×✕*]$")
_NUM = re.compile(r"^\d{1,6}$")
# 重さ。「32.5」「150.0」。小数点があれば、まず重さ。
_WEIGHT = re.compile(r"^\d{1,6}[.,]\d$")
# 名前の切れ端に付く記号
_TAIL = re.compile(r"[.．・…]{2,}$")

CJK = re.compile(r"[ぁ-んァ-ヶ一-龥ー・（）()]")


def _is_cjk(s):
    return bool(s) and bool(CJK.search(s[0]))


def join_words(words):
    """マスの中の語をつなぐ。日本語は詰めて、英字は空白で。"""
    out = ""
    for w in words:
        if not out:
            out = w
            continue
        if _is_cjk(w) or _is_cjk(out[-1]):
            out += w
        else:
            out += " " + w
    return _TAIL.sub("", out).strip()


def find_qty(boxes):
    """個数の札（x65）を探して [(左, 上, 個数)] を返す。"""
    got = []
    used = set()
    for i, (x, y, w, h, t) in enumerate(boxes):
        if i in used:
            continue
        m = _QTY.match(t)
        if m:
            got.append((x, y, int(m.group(1))))
            used.add(i)
            continue
        # 「x」と「65」に切れているとき。すぐ右の数字とくっつける
        if _QTY_MARK.match(t) and i + 1 < len(boxes):
            x2, y2, w2, h2, t2 = boxes[i + 1]
            if _NUM.match(t2) and abs(y2 - y) <= max(h, h2) and 0 <= x2 - (x + w) <= w * 3:
                got.append((x, y, int(t2)))
                used.update((i, i + 1))
    return got


def _cell_size(qty, boxes):
    """マスの大きさを、個数札のならびから割り出す。"""
    xs = sorted(set(q[0] for q in qty))
    ys = sorted(set(q[1] for q in qty))
    dx = [b - a for a, b in zip(xs, xs[1:]) if b - a > 8]
    dy = [b - a for a, b in zip(ys, ys[1:]) if b - a > 8]
    # 縦横のならびが1列しかないときのために、控えの値も用意する
    wide = max((x + w) for x, y, w, h, t in boxes) if boxes else 0
    tall = max((y + h) for x, y, w, h, t in boxes) if boxes else 0
    cw = statistics.median(dx) if dx else max(60, wide)
    ch = statistics.median(dy) if dy else max(60, tall)
    return float(cw), float(ch)


def grid_rows(boxes):
    """位置つきの語から [(名前, 個数)] を作る。"""
    qty = find_qty(boxes)
    if not qty:
        return []
    cw, ch = _cell_size(qty, boxes)
    # 1行の高さ。折り返した名前を2行に分けるのに使う
    line_h = statistics.median([b[3] for b in boxes]) if boxes else 20
    rows = []
    for qx, qy, n in qty:
        # そのマスの中にある語を集める。個数札より下、次のマスの手前まで
        left, right = qx - cw * 0.12, qx + cw * 0.92
        top, bottom = qy, qy + ch * 0.94
        inside = []
        for x, y, w, h, t in boxes:
            cx, cy = x + w / 2.0, y + h / 2.0
            if not (left <= cx <= right and top <= cy <= bottom):
                continue
            if y <= qy + h * 0.6 and x <= qx + cw * 0.45:
                continue                        # 個数札そのもの
            if _WEIGHT.match(t) and cy >= qy + ch * 0.55:
                continue                        # 右下の重さ
            if _NUM.match(t) and cy >= qy + ch * 0.7 and cx >= qx + cw * 0.5:
                continue                        # 小数点が読めなかった重さ
            inside.append((y, x, t))
        if not inside:
            continue
        # 行ごとにまとめてから、左から順に
        inside.sort()
        parts, cur, base = [], [], None
        for y, x, t in inside:
            if base is None or abs(y - base) <= line_h * 0.7:
                base = y if base is None else base
                cur.append((x, t))
            else:
                parts.append(cur)
                cur, base = [(x, t)], y
        if cur:
            parts.append(cur)
        words = []
        for p in parts:
            words += [t for _x, t in sorted(p)]
        name = join_words(words)
        if len(name) >= 2:
            rows.append((name, n))
    return rows


def snap(name, known, cut=0.72):
    """読めた名前を、すでにある名前に寄せる。

    OCRは「ティラノ」を「テイラノ」のように読み違える。一度手で直して
    おけば、次からはその名前に寄る。似ていなければ、読めたまま返す。
    """
    if not name or not known:
        return name, False
    if name in known:
        return name, True
    got = difflib.get_close_matches(name, list(known), n=1, cutoff=cut)
    if got:
        return got[0], True
    return name, False


def read_area(rect, src=""):
    """範囲を写して読む。(語, 品目, 使った設定) を返す。

    いちばん多く品目が取れた設定を採る。1つも取れなければ、しくじり。
    """
    best = ([], [], None)
    for thr, scale in TRIES:
        try:
            boxes = hudread.capture_text(rect, scale=scale, thr=thr, src=src,
                                         boxes=True)
        except hudread.HudError:
            continue
        rows = grid_rows(boxes)
        if len(rows) > len(best[1]):
            best = (boxes, rows, (thr, scale))
        if len(rows) >= 12:        # 十分読めたら、それ以上ためさない
            break
    if best[2] is None:
        raise hudread.HudError("読み取れませんでした。範囲と表示を確かめてください")
    return best
