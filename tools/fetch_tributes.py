# -*- coding: utf-8 -*-
"""ウィキから、マップごとの貢物と必要数を作り直す。

    python tools/fetch_tributes.py

要約させずに wikitext をそのまま解析する。表を人（や小さなモデル）に
読ませると、列を1つずらしただけで別物になり、しかも気づけない。

出来るもの: data/tributes.json
    {"Ragnarok": {"items": [{"name": ..., "G": 1, "B": 1, "A": 1}, ...],
                  "src": "..."} , ...}
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

RAW = "https://ark.wiki.gg/index.php?title=%s&action=raw"
JA_API = "https://ark.wiki.gg/ja/api.php"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "data", "tributes.json")

# 物語マップの表は、ボス名しか書いていない。どのマップのボスかを補う。
BOSS_MAP = {
    "Broodmother Lysrix": "The Island", "Megapithecus": "The Island",
    "Dragon": "The Island", "Overseer": "The Island",
    "Manticore": "Scorched Earth", "Rockwell": "Aberration",
    "Ice Titan": "Extinction", "Desert Titan": "Extinction",
    "Forest Titan": "Extinction", "King Titan": "Extinction",
}
NOT_A_MAP = set(BOSS_MAP) | {"Titan", "Patch Notes", "Boss Arenas", "bosses"}

# アストレオスは一覧表に載っていないので、ボスのページを1つずつ見る。
ASTRAEOS_BOSSES = (
    "Natrix", "Nunatak", "Fractalis", "Cymathoa", "Vulcanithys", "Grendel",
    "Hydraskos", "Shallocis", "Abyssalus", "Minotarchos", "Kroaratos",
    "Colossus", "Thanatos", "Thodes",
)

_LINK = re.compile(r"\[\[([^\]|]+)")
_DLC = re.compile(r"\{\{DLCIcon\|([^}]+)\}\}")


def fetch(page):
    req = urllib.request.Request(RAW % page.replace(" ", "_"),
                                 headers={"User-Agent": "Meridian/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def item_name(cell):
    """{{ItemLink|noDlcIcon=1|Astral Soul}} → Astral Soul"""
    got = re.findall(r"\{\{ItemLink\|([^}]*)\}\}", cell)
    if not got:
        return ""
    parts = [p.strip() for p in got[0].split("|") if "=" not in p]
    return parts[-1] if parts else ""


def num(cell):
    """「10」「colspan=3 | 1」「✖」「-」から数を取る。無ければ 0。"""
    t = re.sub(r'style\s*=\s*"[^"]*"', "", cell)
    t = re.sub(r'colspan\s*=\s*"?\d+"?', "", t).replace("|", " ")
    m = re.search(r"\d+", t)
    return int(m.group(0)) if m else 0


def split_cells(line):
    """1行を「||」で割る。colspan は (値, 何列ぶん) にする。"""
    out = []
    for raw in line.split("||"):
        raw = raw.strip()
        m = re.match(r'colspan\s*=\s*"?(\d+)"?\s*(?:style\s*=\s*"[^"]*")?\s*\|(.*)$',
                     raw)
        if m:
            out.append((m.group(2).strip(), int(m.group(1))))
        else:
            out.append((raw, 1))
    return out


def head_map(head):
    """見出しから、どのマップかを決める。"""
    for cand in _LINK.findall(head):
        if cand not in NOT_A_MAP and not cand.startswith("Patch"):
            return cand
    for boss, mp in BOSS_MAP.items():
        if boss in head:
            return mp
    d = _DLC.search(head)
    return d.group(1).strip() if d else head[:40]


def parse_wide(text):
    """マップ×難易度が横に並ぶ大きな表（story / mods）を読む。"""
    lines = text.splitlines()
    groups, i = [], 0
    # colspan がちょうど3の見出しだけを拾う。
    # "colspan=3" の部分一致だと、表全体の幅 colspan="39" にも当たる。
    head = re.compile(r"^!\s*colspan\s*=\s*\"?3\"?\s*\|")
    for i, ln in enumerate(lines):
        if head.match(ln):
            break
    while i < len(lines) and head.match(lines[i]):
        groups.append(lines[i].split("|", 1)[1].strip())
        i += 1
    got = {}          # (マップ, ボス) -> {品目: {G,B,A}}
    for ln in lines:
        if not ln.startswith("| style=") or "ItemLink" not in ln:
            continue
        cells = split_cells(ln)
        name = item_name(cells[0][0])
        if not name:
            continue
        col = 0
        for value, span in cells[1:]:
            n = num(value)
            for k in range(span):
                grp, diff = (col + k) // 3, "GBA"[(col + k) % 3]
                if grp < len(groups) and n:
                    head = groups[grp]
                    key = (head_map(head), head_boss(head))
                    got.setdefault(key, {}).setdefault(
                        name, {"G": 0, "B": 0, "A": 0})[diff] = n
            col += span
    return got


def head_boss(head):
    """見出しから、ボスの名前を取り出す。「ドラゴン＋マンティコア」もある。"""
    got = re.findall(r"\{\{(?:ItemLink|IconLink)\|([^}|]+)", head)
    got = [g.strip() for g in got if g.strip()]
    if got:
        return "+".join(got)
    t = re.sub(r"\{\{[^}]*\}\}", "", head)
    t = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", r"\1", t)
    return t.strip(" |") or "?"


def parse_boss(text):
    """ボス1体のページの「Tribute Requirements」を読む。

    書き方が3通りある。
      * 1行に「| 名前 || G || B || A」と並ぶもの
      * セルを1行ずつ「|名前」「|5」「|10」「|15」と書くもの
      * 難易度が無く「必要数」だけのもの
    どれでも読めるように、行を「|-」で区切って升に分ける。
    """
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        t = ln.strip()
        if re.match(r"^=+\s*Tribute", t, re.I) or \
                "you will need the following tributes" in t or \
                "needed to summon" in t or "needed to open" in t:
            start = i
            break
    if start is None:
        return {}
    three, rows, cur = None, [], []
    for ln in lines[start:start + 120]:
        t = ln.strip()
        if t.startswith("|}"):
            rows.append(cur)
            break
        if t.startswith("!"):
            if "Gamma" in t or "gamma" in t:
                three = True
            continue
        if t.startswith("|-"):
            rows.append(cur)
            cur = []
            continue
        if t.startswith("|"):
            body = t[1:]
            if "||" in body:
                cur += [c.strip() for c in body.split("||")]
            else:
                cur.append(body.strip())
    else:
        rows.append(cur)

    got = {}
    for cells in rows:
        if not cells or "ItemLink" not in cells[0]:
            continue
        name = item_name(cells[0])
        if not name:
            continue
        vals = []
        for c in cells[1:]:
            m = re.match(r'colspan\s*=\s*"?(\d+)"?\s*(?:style\s*=\s*"[^"]*")?\s*\|(.*)$',
                         c)
            if m:
                vals += [num(m.group(2))] * int(m.group(1))
            else:
                vals.append(num(c))
        if not vals:
            continue
        if three and len(vals) >= 3:
            g, b, a = vals[0], vals[1], vals[2]
        else:
            g = b = a = vals[0]
        if g or b or a:
            got[name] = {"G": g, "B": b, "A": a}
    return got


def ja_names(names):
    """英語名 → 日本語名。ja版の記事名（転送先）がそのまま日本語名になる。

    ゲームの表記と同じものが返る。スクショから読んだ名前と突き合うので、
    英語のまま持たせるより、こちらのほうがずっと使える。
    日本語ページが無いもの（Astral Soul など）は英語のまま。
    """
    out = {}
    names = sorted(set(names))
    for i in range(0, len(names), 40):        # APIは一度に50件まで
        chunk = names[i:i + 40]
        url = (JA_API + "?action=query&redirects=1&format=json&titles="
               + "|".join(urllib.parse.quote(n) for n in chunk))
        try:
            req = urllib.request.Request(url,
                                         headers={"User-Agent": "Meridian/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            print("   日本語名が引けず: %s" % e)
            continue
        for row in d.get("query", {}).get("redirects", []):
            out[row["from"]] = row["to"]
    return out


def main():
    out = {}      # マップ -> {"src": .., "bosses": {ボス: {品目: {G,B,A}}}}

    def add(mp, boss, items, src):
        box = out.setdefault(mp, {"src": src, "bosses": {}})
        cur = box["bosses"].setdefault(boss, {})
        for name, d in items.items():
            row = cur.setdefault(name, {"G": 0, "B": 0, "A": 0})
            for k in "GBA":
                row[k] = max(row[k], d[k])

    for page in ("Table of story map tributes", "Table of official mod tributes"):
        got = parse_wide(fetch(page))
        for (mp, boss), items in got.items():
            add(mp, boss, items, page)
        print("%-34s → %d のボス" % (page, len(got)))

    # アストレオスは一覧に無いので、ボスのページを1体ずつ
    for boss in ASTRAEOS_BOSSES:
        try:
            items = parse_boss(fetch(boss))
        except Exception as e:
            print("   %-14s 取れず（%s）" % (boss, e))
            continue
        print("   %-14s %d品目" % (boss, len(items)))
        if items:
            add("Astraeos", boss, items, "各ボスのページ")

    # 品名とボス名を日本語にする
    every, bosses = set(), set()
    for box in out.values():
        for boss, items in box["bosses"].items():
            bosses.update(boss.split("+"))
            every |= set(items)
    print("\n日本語名を引きます（品目 %d ／ ボス %d）…" % (len(every), len(bosses)))
    ja = ja_names(every | bosses)
    print("   %d件に日本語名がありました" % len(ja))

    def boss_ja(boss):
        return "＋".join(ja.get(b, b) for b in boss.split("+"))

    final = {}
    for mp, box in out.items():
        rows = []
        for boss, items in sorted(box["bosses"].items()):
            rows.append({
                "boss": boss, "ja": boss_ja(boss),
                "items": [dict(name=ja.get(n, n), en=n, **d)
                          for n, d in sorted(items.items())]})
        final[mp] = {"bosses": rows, "src": box["src"]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8").write(
        json.dumps(final, ensure_ascii=False, indent=1, sort_keys=True))
    print("\n書き出し: %s（%d マップ）" % (OUT, len(final)))
    for mp in sorted(final):
        n = sum(len(b["items"]) for b in final[mp]["bosses"])
        print("   %-16s ボス%d体 / のべ%d品目  (%s)"
              % (mp, len(final[mp]["bosses"]), n, final[mp]["src"]))
        for b in final[mp]["bosses"]:
            print("        %-34s %d品目" % (b["ja"], len(b["items"])))


if __name__ == "__main__":
    sys.exit(main())
