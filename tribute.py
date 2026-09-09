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

import io
import json
import time

# アーティファクト24種。日本語名は ja版ウィキの記事名＝ゲームの表記。
# 推測で書いていたころは「暴食」を「捕食者」、「天帝」を「空の王」などと
# 取り違えていた。tools/fetch_tributes.py と同じ引きかたで取り直したもの。
ARTIFACTS = (
    ("Brute", "野獣のアーティファクト"),
    ("Chaos", ""),
    ("Clever", "賢者のアーティファクト"),
    ("Crag", "岩山のアーティファクト"),
    ("Cunning", "狡猾のアーティファクト"),
    ("Depths", "落のアーティファクト"),
    ("Destroyer", "破壊者のアーティファクト"),
    ("Devious", "邪悪のアーティファクト"),
    ("Devourer", "暴食のアーティファクト"),
    ("Fallen", ""),
    ("Gatekeeper", "門番のアーティファクト"),
    ("Growth", ""),
    ("Hunter", "狩人のアーティファクト"),
    ("Immune", "免疫のアーティファクト"),
    ("Lost", "迷人のアーティファクト"),
    ("Massive", "大物のアーティファクト"),
    ("Mighty", ""),
    ("Pack", "群集のアーティファクト"),
    ("Seeking", ""),
    ("Shadows", "影のアーティファクト"),
    ("Skylord", "天帝のアーティファクト"),
    ("Stalker", "追跡者のアーティファクト"),
    ("Strong", "強者のアーティファクト"),
    ("Void", "虚無のアーティファクト"),
)


def artifact_name(key):
    """アーティファクトの見せかたを1つに決める。

    ゲームに出る日本語名をそのまま使う。スクショから読んだ名前と
    突き合うので、こちらのほうが都合がよい。
    """
    for en, ja in ARTIFACTS:
        if en == key:
            return ja or ("Artifact of the %s" % en)
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


# ------------------------------------------------ 知っている貢物
# data/tributes.json は tools/fetch_tributes.py がウィキから作る。
# 名前はゲームと同じ日本語（日本語ページが無いものは英語のまま）。
DIFFS = (("G", "ガンマ"), ("B", "ベータ"), ("A", "アルファ"))
_KNOWN = None


def diff_label(key):
    for k, lbl in DIFFS:
        if k == key:
            return lbl
    return key


def load_known(path):
    """一覧を読み込む。無くても動くように、失敗したら空にする。"""
    global _KNOWN
    if _KNOWN is None:
        try:
            with io.open(path, encoding="utf-8") as f:
                _KNOWN = json.load(f)
        except Exception:
            _KNOWN = {}
    return _KNOWN


def known_map(name):
    """持ち物帳のマップ名から、一覧のどのマップかを見つける。

    英語名でも日本語名でも引けるようにする。
    """
    if not _KNOWN:
        return ""
    if name in _KNOWN:
        return name
    key = norm(name)
    for mp in _KNOWN:
        if norm(mp) == key:
            return mp
    try:
        import gametime
        for mp in _KNOWN:
            if norm(gametime.map_label(mp)) == key:
                return mp
    except Exception:
        pass
    return ""


ALL_BOSSES = "＊"          # 「このマップのボスぜんぶ」


def known_bosses(map_name):
    """そのマップのボス。[(見出しの名前, 中の名前)]。"""
    mp = known_map(map_name)
    if not mp:
        return []
    return [(b.get("ja") or b.get("boss"), b.get("boss"))
            for b in _KNOWN[mp].get("bosses", [])]


def known_items(map_name, diff="B", boss=None):
    """そのマップ・そのボス・その難易度で要る貢物。

    boss を渡さない（または ALL_BOSSES）と、そのマップのボスぜんぶを
    まとめたものになる。同じ品目は、いちばん多く要るボスに合わせる。
    """
    mp = known_map(map_name)
    if not mp:
        return []
    need = {}
    kinds = {}
    for b in _KNOWN[mp].get("bosses", []):
        if boss and boss != ALL_BOSSES and b.get("boss") != boss:
            continue
        for row in b.get("items", []):
            n = int(row.get(diff) or 0)
            if n <= 0:
                continue
            name = row.get("name") or row.get("en") or ""
            need[name] = max(need.get(name, 0), n)
            kinds[name] = ("artifact"
                           if "Artifact of" in (row.get("en") or "")
                           else "tribute")
    return [(name, need[name], kinds[name]) for name in sorted(need)]


def known_src(map_name):
    mp = known_map(map_name)
    return _KNOWN.get(mp, {}).get("src", "") if mp else ""


# ------------------------------------------------ 検索用の字の均し
# 「アロサウルスの脳」を探すのに、いちいち変換してカタカナにするのは面倒。
# 「あろ」でも「aro」でも当たるように、くらべる前に字を寄せておく。

# 半角カナ → 全角カナ（濁点は付け直す）
_HANKAKU = (
    ("ｶﾞ", "ガ"), ("ｷﾞ", "ギ"), ("ｸﾞ", "グ"), ("ｹﾞ", "ゲ"), ("ｺﾞ", "ゴ"),
    ("ｻﾞ", "ザ"), ("ｼﾞ", "ジ"), ("ｽﾞ", "ズ"), ("ｾﾞ", "ゼ"), ("ｿﾞ", "ゾ"),
    ("ﾀﾞ", "ダ"), ("ﾁﾞ", "ヂ"), ("ﾂﾞ", "ヅ"), ("ﾃﾞ", "デ"), ("ﾄﾞ", "ド"),
    ("ﾊﾞ", "バ"), ("ﾋﾞ", "ビ"), ("ﾌﾞ", "ブ"), ("ﾍﾞ", "ベ"), ("ﾎﾞ", "ボ"),
    ("ﾊﾟ", "パ"), ("ﾋﾟ", "ピ"), ("ﾌﾟ", "プ"), ("ﾍﾟ", "ペ"), ("ﾎﾟ", "ポ"),
)
_HAN1 = str.maketrans(
    "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝｧｨｩｪｫｯｬｭｮｰ",
    "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンァィゥェォッャュョー")

# ローマ字。長いものから当てる（kya を k+ya と読まないように）
_ROMA = {
    "kya": "キャ", "kyu": "キュ", "kyo": "キョ", "sha": "シャ", "shu": "シュ",
    "sho": "ショ", "shi": "シ", "cha": "チャ", "chu": "チュ", "cho": "チョ",
    "chi": "チ", "tsu": "ツ", "nya": "ニャ", "nyu": "ニュ", "nyo": "ニョ",
    "hya": "ヒャ", "hyu": "ヒュ", "hyo": "ヒョ", "mya": "ミャ", "myu": "ミュ",
    "myo": "ミョ", "rya": "リャ", "ryu": "リュ", "ryo": "リョ", "gya": "ギャ",
    "gyu": "ギュ", "gyo": "ギョ", "ja": "ジャ", "ju": "ジュ", "jo": "ジョ",
    "ji": "ジ", "bya": "ビャ", "byu": "ビュ", "byo": "ビョ", "pya": "ピャ",
    "pyu": "ピュ", "pyo": "ピョ", "fu": "フ", "shi": "シ",
    "ka": "カ", "ki": "キ", "ku": "ク", "ke": "ケ", "ko": "コ",
    "sa": "サ", "su": "ス", "se": "セ", "so": "ソ",
    "ta": "タ", "te": "テ", "to": "ト", "ti": "チ", "tu": "ツ",
    "na": "ナ", "ni": "ニ", "nu": "ヌ", "ne": "ネ", "no": "ノ",
    "ha": "ハ", "hi": "ヒ", "he": "ヘ", "ho": "ホ", "hu": "フ",
    "ma": "マ", "mi": "ミ", "mu": "ム", "me": "メ", "mo": "モ",
    "ya": "ヤ", "yu": "ユ", "yo": "ヨ",
    "ra": "ラ", "ri": "リ", "ru": "ル", "re": "レ", "ro": "ロ",
    "wa": "ワ", "wo": "ヲ",
    "ga": "ガ", "gi": "ギ", "gu": "グ", "ge": "ゲ", "go": "ゴ",
    "za": "ザ", "zu": "ズ", "ze": "ゼ", "zo": "ゾ", "zi": "ジ",
    "da": "ダ", "di": "ヂ", "du": "ヅ", "de": "デ", "do": "ド",
    "ba": "バ", "bi": "ビ", "bu": "ブ", "be": "ベ", "bo": "ボ",
    "pa": "パ", "pi": "ピ", "pu": "プ", "pe": "ペ", "po": "ポ",
    "a": "ア", "i": "イ", "u": "ウ", "e": "エ", "o": "オ", "n": "ン",
    "-": "ー",
    # 外来語の音。ARKの品名はカタカナが多いので、ここが要る
    "thi": "ティ", "the": "テェ", "tha": "テャ", "thu": "テュ",
    "dhi": "ディ", "dha": "デャ", "dhu": "デュ", "dho": "デョ",
    "twu": "トゥ", "dwu": "ドゥ", "tyu": "チュ", "tya": "チャ", "tyo": "チョ",
    "sya": "シャ", "syu": "シュ", "syo": "ショ", "jya": "ジャ",
    "jyu": "ジュ", "jyo": "ジョ", "che": "チェ", "she": "シェ", "je": "ジェ",
    "fa": "ファ", "fi": "フィ", "fe": "フェ", "fo": "フォ", "fyu": "フュ",
    "va": "ヴァ", "vi": "ヴィ", "vu": "ヴ", "ve": "ヴェ", "vo": "ヴォ",
    "wi": "ウィ", "we": "ウェ", "wo": "ヲ",
    "tsa": "ツァ", "tse": "ツェ", "tso": "ツォ",
    "xa": "ァ", "xi": "ィ", "xu": "ゥ", "xe": "ェ", "xo": "ォ",
    "xya": "ャ", "xyu": "ュ", "xyo": "ョ", "xtu": "ッ",
    "la": "ァ", "li": "ィ", "lu": "ゥ", "le": "ェ", "lo": "ォ",
}


def to_kana(s):
    """ひらがな・半角カナを、全角カタカナに寄せる。"""
    t = s or ""
    for a, b in _HANKAKU:
        t = t.replace(a, b)
    t = t.translate(_HAN1)
    # ひらがな → カタカナ（コード上で 0x60 ぶん離れている）
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in t)


def from_romaji(s):
    """ローマ字をカタカナにする。読めない字はそのまま置いておく。

    打ちかけの「ar」のようなものも扱う。最後の1字が子音なら、
    そこは切り落として「ア」まででくらべる。
    """
    t = (s or "").lower()
    out, i = "", 0
    while i < len(t):
        if t[i] == "n" and i + 1 < len(t) and t[i + 1] not in "aiueoy":
            out += "ン"
            i += 1
            continue
        # 「ssa」のような詰まる音
        if (i + 1 < len(t) and t[i] == t[i + 1] and t[i] in
                "kstnhmyrwgzdbpcfj"):
            out += "ッ"
            i += 1
            continue
        for size in (3, 2, 1):
            got = _ROMA.get(t[i:i + size])
            if got:
                out += got
                i += size
                break
        else:
            out += t[i]
            i += 1
    return out


def search_key(s):
    """くらべる用の字。空白を落として、カタカナに寄せて、小文字に。"""
    t = to_kana((s or "").strip())
    t = t.translate(str.maketrans("０１２３４５６７８９（）",
                                  "0123456789()"))
    return "".join(t.split()).lower()


def hit(query, name):
    """探している字が、その名前に入っているか。

    ひらがなで打っても、ローマ字で打っても当たるようにする。
    ローマ字は、英語のままの品名（Astral Soul）とぶつかるので、
    そのままの字で当たらなかったときだけ試す。
    """
    q = search_key(query)
    if not q:
        return True
    key = search_key(name)
    if q in key:
        return True
    if q.isascii() and q.isalpha():
        return search_key(from_romaji(q)) in key
    return False
