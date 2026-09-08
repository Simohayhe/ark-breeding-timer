# -*- coding: utf-8 -*-
"""🏺 貢物とアーティファクトの持ち物帳（データのほう）。

マップごとに「なにを何個持っているか」と「何個いるか」を覚えておくだけ。

品目の名前は **ゲームの表記をそのまま** 使う。ここでウィキの表を写して
焼き込むのはやめた。写し間違いに気づけないし、アップデートで変わったら
直しようがない。持ち物はスクショから取り込むか、自分で足す。

アーティファクトの名前だけは、英語名がはっきり決まっていて増えないので
「よくある名前」として候補に出す。選ぶのは自由で、強制はしない。
"""
from __future__ import annotations

import time

# アーティファクトの英語名（コミュニティで通じるのはこの並び）。
# 日本語名は人によって表記ゆれがあるので、こちらは目安として添えるだけ。
ARTIFACTS = (
    ("Brute", "猛者"),
    ("Chaos", "混沌"),
    ("Clever", "賢者"),
    ("Crag", "岩山"),
    ("Cunning", "狡猾"),
    ("Depths", "深淵"),
    ("Destroyer", "破壊者"),
    ("Devious", "邪知"),
    ("Devourer", "捕食者"),
    ("Fallen", "堕天"),
    ("Gatekeeper", "門番"),
    ("Growth", "成長"),
    ("Hunter", "狩人"),
    ("Immune", "免疫"),
    ("Lost", "喪失"),
    ("Massive", "巨大"),
    ("Mighty", "強大"),
    ("Pack", "群れ"),
    ("Seeking", "探求"),
    ("Shadows", "影"),
    ("Skylord", "空の王"),
    ("Stalker", "追跡者"),
    ("Strong", "剛力"),
    ("Void", "虚無"),
)


def artifact_name(key):
    """アーティファクトの見せかたを1つに決める。"""
    for en, ja in ARTIFACTS:
        if en == key:
            return "Artifact of the %s（%s）" % (en, ja)
    return key


class Item:
    """1品目。持っている数と、いる数。"""

    FIELDS = ("name", "have", "need", "kind", "note", "seen")

    def __init__(self, name, have=0, need=0, kind="", note="", seen=0.0):
        self.name = name
        self.have = int(have or 0)
        self.need = int(need or 0)
        self.kind = kind or ""          # "artifact" / "tribute" / ""
        self.note = note or ""
        self.seen = float(seen or 0.0)  # 最後に数が変わった時刻

    # ---- 数をいじる ----
    def set_have(self, n):
        n = max(0, int(n))
        if n != self.have:
            self.have = n
            self.seen = time.time()

    def add(self, d):
        self.set_have(self.have + int(d))

    # ---- 見せかた ----
    def short(self):
        """足りているか。(足りない数, 文字) を返す。"""
        if self.need <= 0:
            return 0, "%d個" % self.have
        left = max(0, self.need - self.have)
        if left == 0:
            return 0, "%d / %d 個 ✔" % (self.have, self.need)
        return left, "%d / %d 個（あと%d）" % (self.have, self.need, left)

    def to_dict(self):
        return {k: getattr(self, k) for k in self.FIELDS}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("name", ""), d.get("have", 0), d.get("need", 0),
                   d.get("kind", ""), d.get("note", ""), d.get("seen", 0.0))


class Book:
    """マップごとの持ち物帳。

    マップ名は時計と同じ名前（Astraeos など）を使う。見張っていない
    マップも書けるように、名前は自由。
    """

    def __init__(self, data=None):
        self.maps = {}          # マップ名 -> [Item]
        self.order = []         # 並び順
        if data:
            self.load(data)

    # ---- 出し入れ ----
    def load(self, data):
        self.maps, self.order = {}, []
        for name in data.get("order", []):
            rows = data.get("maps", {}).get(name) or []
            self.maps[name] = [Item.from_dict(r) for r in rows]
            self.order.append(name)
        # order に入っていないマップも拾う（手で書き足したとき用）
        for name, rows in (data.get("maps") or {}).items():
            if name not in self.maps:
                self.maps[name] = [Item.from_dict(r) for r in rows]
                self.order.append(name)

    def to_dict(self):
        return {"order": list(self.order),
                "maps": {n: [it.to_dict() for it in self.maps.get(n, [])]
                         for n in self.order}}

    # ---- マップ ----
    def add_map(self, name):
        name = (name or "").strip()
        if not name:
            return None
        if name not in self.maps:
            self.maps[name] = []
            self.order.append(name)
        return name

    def drop_map(self, name):
        self.maps.pop(name, None)
        if name in self.order:
            self.order.remove(name)

    def items(self, name):
        return self.maps.get(name) or []

    # ---- 品目 ----
    def find(self, name, item_name):
        key = norm(item_name)
        for it in self.items(name):
            if norm(it.name) == key:
                return it
        return None

    def put(self, map_name, item_name, have=None, add=None, need=None,
            kind=""):
        """あれば足し、なければ作る。取り込みでも手入力でもここを通す。"""
        self.add_map(map_name)
        it = self.find(map_name, item_name)
        if it is None:
            it = Item(item_name.strip(), 0, 0, kind)
            self.maps[map_name].append(it)
        if kind and not it.kind:
            it.kind = kind
        if have is not None:
            it.set_have(have)
        if add:
            it.add(add)
        if need is not None:
            it.need = max(0, int(need))
        return it

    def drop(self, map_name, item):
        rows = self.maps.get(map_name)
        if rows and item in rows:
            rows.remove(item)

    def sort(self, map_name):
        """アーティファクトを先に、あとは名前順。"""
        rows = self.maps.get(map_name)
        if rows:
            rows.sort(key=lambda i: (0 if i.kind == "artifact" else 1,
                                     i.name.lower()))

    # ---- まとめ ----
    def summary(self, map_name):
        rows = self.items(map_name)
        if not rows:
            return "まだ何も入っていません"
        art = sum(1 for i in rows if i.kind == "artifact")
        short = [i for i in rows if i.need > 0 and i.have < i.need]
        head = "%d品目" % len(rows)
        if art:
            head += "（うちアーティファクト %d）" % art
        if not short:
            need_any = any(i.need > 0 for i in rows)
            return head + ("　ぜんぶ足りています ✔" if need_any else "")
        return head + "　足りないもの %d" % len(short)


def norm(s):
    """名前くらべ用。空白と大文字小文字と全角の差を無視する。"""
    t = (s or "").strip().lower()
    t = t.translate(str.maketrans("０１２３４５６７８９（）",
                                  "0123456789()"))
    return "".join(t.split())
