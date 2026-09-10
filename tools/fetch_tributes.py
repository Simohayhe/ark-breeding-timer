# -*- coding: utf-8 -*-
"""ウィキから、マップごとの貢物と必要数を作り直す（ASA版）。

    python tools/fetch_tributes.py

要約させずに wikitext をそのまま解析する。表を人（や小さなモデル）に
読ませると、列を1つずらしただけで別物になり、しかも気づけない。

大事なのは **どのマップにどのボスがいるか** をこちらで決めないこと。
ASE と ASA でボスが違う（ラグナロクは ASE がドラゴン＋マンティコアで、
ASA はヌナタク。バルゲロは ASA でグレンデル）。ウィキのマップページが
sa / se を分けて書いているので、そこから取る。

必要数はボスのページから。ボスのページはマップごとのタブに分かれている
ことがあるので、そのマップのタブを選ぶ。
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

MAPS = ("The Island", "Scorched Earth", "Aberration", "Extinction",
        "The Center", "Ragnarok", "Valguero", "Astraeos", "Lost Island",
        "Fjordur", "Crystal Isles", "Aquatica", "Lost Colony")

# ボスの一覧に混ざるが、貢物で呼ぶ相手ではないもの
NOT_BOSS = {"Iceworm Queen", "Lava Elemental", "Rock Elemental"}

# マップページの Bosses に載っていても、ポータルで呼ぶ相手ではないもの。
# バルゲロのブルードマザーは洞窟に湧いているだけで、貢物は要らない。
# ページの書き方では見分けられないので、ここに書いておく。
NOT_BOSS_ON = {("Valguero", "Broodmother Lysrix")}


def fetch(page):
    req = urllib.request.Request(
        RAW % urllib.parse.quote(page.replace(" ", "_")),
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


# ------------------------------------------------ マップ → ボス
def bosses_of(text, map_name=""):
    """マップページの「Bosses」から、ASAにいるボスを拾う。

    ページはこう書かれている。

        ==== Bosses ====
        {{ItemList|Iceworm Queen|Lava Elemental}}
        {{gamelink|sa}} exclusive:
        {{ItemList|columnwidth=15em|Nunatak}}
        {{gamelink|se}} exclusive:
        {{ItemList|columnwidth=15em|Dragon|Manticore}}

    印の無いものと sa のものを採り、se のものは捨てる。
    """
    out, lines = [], text.splitlines()
    i, n = 0, len(lines)
    # 「Other Spawns」の下にある Bosses を落とす手も考えたが、それだと
    # センターのブルードマザーとメガピテクス（本物のボス）まで落ちる。
    # 書き方では見分けられないので、除くものは NOT_BOSS_ON に書く。
    while i < n:
        if not re.match(r"^=+\s*Bosses\s*=+\s*$", lines[i].strip()):
            i += 1
            continue
        i += 1
        mode = "both"
        while i < n:
            t = lines[i].strip()
            if t.startswith("=") and "Bosses" not in t:
                break                          # 次の見出しで終わり
            if "{{gamelink|sa}}" in t:
                mode = "sa"
            elif "{{gamelink|se}}" in t:
                mode = "se"
            elif t.startswith("{{ItemList|"):
                if mode != "se":
                    body = t[len("{{ItemList|"):].rstrip("}")
                    for part in body.split("|"):
                        part = part.strip()
                        if (part and "=" not in part
                                and part not in NOT_BOSS
                                and (map_name, part) not in NOT_BOSS_ON):
                            out.append(part)
            i += 1
    seen, keep = set(), []
    for b in out:
        if b not in seen:
            seen.add(b)
            keep.append(b)
    return keep


# ------------------------------------------------ ボス → 必要数
def tabs_of(chunk):
    """<tabber> を、(タブの名前, 中身) に割る。無ければ 1つだけ返す。"""
    if "<tabber>" not in chunk:
        return [("", chunk)]
    body = chunk.split("<tabber>", 1)[1].split("</tabber>", 1)[0]
    out = []
    for part in body.split("|-|"):
        m = re.match(r"\s*([^=\n]{1,40})=", part)
        if m:
            out.append((m.group(1).strip(), part[m.end():]))
        else:
            out.append(("", part))
    return out


def rows_of(chunk):
    """表を升に割って、{名前: {G,B,A}} にする。

    1行に「| 名前 || G || B || A」と並ぶものと、セルを1行ずつ書くものが
    あるので、行を「|-」で区切ってから読む。
    """
    three, rows, cur = None, [], []
    for ln in chunk.splitlines():
        t = ln.strip()
        if t.startswith("|}"):
            rows.append(cur)
            cur = []
            continue
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
            cur += ([c.strip() for c in body.split("||")] if "||" in body
                    else [body.strip()])
    rows.append(cur)

    got = {}
    for cells in rows:
        if not cells or "ItemLink" not in cells[0]:
            continue
        name = item_name(cells[0])
        if not name or "Player Level" in cells[0]:
            continue
        vals = []
        for c in cells[1:]:
            m = re.match(r'colspan\s*=\s*"?(\d+)"?\s*'
                         r'(?:style\s*=\s*"[^"]*")?\s*\|(.*)$', c)
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


def tribute_of(text, map_name):
    """ボスのページから、そのマップぶんの必要数を読む。"""
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
    end = len(lines)
    for j in range(start + 1, len(lines)):
        t = lines[j].strip()
        if t.startswith("=") and not re.match(r"^=+\s*Tribute", t, re.I):
            end = j
            break
    chunk = "\n".join(lines[start:end])
    tabs = tabs_of(chunk)
    pick = None
    for name, part in tabs:
        if name and map_name.lower() in name.lower():
            pick = part
            break
    if pick is None:
        for name, part in tabs:
            if not name or "any map" in name.lower():
                pick = part
                break
    return rows_of(pick if pick is not None else tabs[0][1])


# ------------------------------------------------ 日本語名
TIERS = (("Gamma", "ガンマ"), ("Beta", "ベータ"), ("Alpha", "アルファ"))


def split_tier(en):
    for word, ja in TIERS:
        if en.startswith(word + " "):
            return ja, en[len(word) + 1:]
        if en.endswith("(%s)" % word):
            return ja, en[:-len(word) - 2].strip()
    return "", en


def ja_names(names):
    """英語名 → 日本語名。ja版の記事名（転送先）がそのまま日本語名になる。"""
    out = {}
    names = sorted(set(names))
    for i in range(0, len(names), 40):
        chunk = names[i:i + 40]
        url = (JA_API + "?action=query&redirects=1&format=json&titles="
               + "|".join(urllib.parse.quote(n) for n in chunk))
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Meridian/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            print("   日本語名が引けず: %s" % e)
            continue
        for row in d.get("query", {}).get("redirects", []):
            out[row["from"]] = row["to"]
    return out


def unclash(ja):
    """同じ日本語名に潰れたものを、見分けられるようにする。

    ボスのトロフィーは Gamma / Beta / Alpha で別のアイテムなのに、
    ja版ウィキではどれも同じ記事に飛ぶ。難易度の別を後ろに足して分ける。
    """
    same = {}
    for en, name in ja.items():
        same.setdefault(name, []).append(en)
    for name, ens in same.items():
        if len(ens) < 2:
            continue
        for en in ens:
            tier, _rest = split_tier(en)
            if tier:
                ja[en] = "%s（%s）" % (name, tier)
    return ja


def main():
    out = {}
    for mp in MAPS:
        try:
            page = fetch(mp)
        except Exception as e:
            print("%-16s 取れず（%s）" % (mp, e))
            continue
        names = bosses_of(page, mp)
        print("%-16s ボス %d: %s" % (mp, len(names), "、".join(names)))
        got = {}
        for boss in names:
            try:
                items = tribute_of(fetch(boss), mp)
            except Exception as e:
                print("      %-26s 取れず（%s）" % (boss, e))
                continue
            if items:
                got[boss] = items
            print("      %-26s %d品目%s"
                  % (boss, len(items), "" if items else "  ← 貢物なし"))
        if got:
            out[mp] = got

    every, bosses = set(), set()
    for got in out.values():
        for boss, items in got.items():
            bosses.add(boss)
            every |= set(items)
    print("\n日本語名を引きます（品目 %d ／ ボス %d）…" % (len(every), len(bosses)))
    ja = unclash(ja_names(every | bosses))
    print("   %d件に日本語名がありました" % len(ja))

    final = {}
    for mp, got in out.items():
        rows = []
        for boss, items in sorted(got.items()):
            rows.append({
                "boss": boss, "ja": ja.get(boss, boss),
                "items": [dict(name=ja.get(n, n), en=n, **d)
                          for n, d in sorted(items.items())]})
        final[mp] = {"bosses": rows, "src": "マップページ＋各ボスのページ"}

    try:
        sys.path.insert(0, HERE)
        import tribute as tb
        lack = tb.missing_readings({it["name"] for mp in final.values()
                                    for b in mp["bosses"] for it in b["items"]})
        print("\n読みを持っていない漢字: " + ("、".join(lack) if lack else "なし"))
        if lack:
            print("   tribute.py の READINGS に足してください")
    except Exception as e:
        print("読みの確かめができず: %s" % e)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8").write(
        json.dumps(final, ensure_ascii=False, indent=1, sort_keys=True))
    print("\n書き出し: %s（%d マップ）" % (OUT, len(final)))
    for mp in sorted(final):
        print("   %-16s ボス%d体" % (mp, len(final[mp]["bosses"])))
        for b in final[mp]["bosses"]:
            print("        %-30s %d品目" % (b["ja"], len(b["items"])))


if __name__ == "__main__":
    sys.exit(main())
