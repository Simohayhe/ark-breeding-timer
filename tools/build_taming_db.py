# -*- coding: utf-8 -*-
"""ARKStatsExtractor から テイム計算用のデータを抜き出して data/taming.json を作る。

必要なもの:
  values/values.json      … taming ブロックと気絶値のステータス
  values/ASA-values.json  … ASA の追加・上書き
  tamingFoodData.json     … 何を食べるか、食料ごとの値（default に共通テーブル）

    python tools/build_taming_db.py [values.json] [ASA-values.json] [tamingFoodData.json]
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
_REL = os.path.join(os.path.dirname(PROJ), "ARKStatsExtractor", "ARKBreedingStats",
                    "json")
DEFAULT_ASE = os.path.join(_REL, "values", "values.json")
DEFAULT_ASA = os.path.join(_REL, "values", "ASA-values.json")
DEFAULT_FOOD = os.path.join(_REL, "tamingFoodData.json")

STAT_TORPIDITY = 2   # fullStatsRaw の並びで気絶値は3番目

# ASE 時代にしか無い餌。このアプリは ASA 向けなので候補から外す。
#   "Kibble" = v293 以前の統合キブル。いまのキブルは6段階（＋強化版）だけ。
ASE_ONLY_FOODS = {"Kibble"}

SKIP_NAME_PARTS = ("VR ", "Ghost", "Corrupted", "Malfunctioned", "Alpha ", "Brute ",
                   "Dinotar")
SKIP_BP_PARTS = ("/Missions/", "TekCave", "/Gauntlet", "/Boss/")

# 日本語の食べ物名（検索と表示用）。無いものは英語のまま出す。
FOOD_JP = {
    "Raw Meat": "生肉",
    "Cooked Meat": "焼いた肉",
    "Cooked Meat Jerky": "干し肉",
    "Raw Prime Meat": "高級な生肉",
    "Cooked Prime Meat": "高級な焼いた肉",
    "Prime Meat Jerky": "高級な干し肉",
    "Raw Fish Meat": "生魚",
    "Cooked Fish Meat": "焼いた魚",
    "Raw Prime Fish Meat": "高級な生魚",
    "Cooked Prime Fish Meat": "高級な焼いた魚",
    "Raw Mutton": "生のマトン",
    "Cooked Lamb Chop": "ラムチョップ",
    "Spoiled Meat": "腐った肉",
    "Mejoberry": "メジョベリー",
    "Berries": "ベリー",
    "Amarberry": "アマーベリー",
    "Azulberry": "アズルベリー",
    "Tintoberry": "ティントベリー",
    "Vegetables": "野菜",
    "Crops": "作物",
    "Sweet Vegetable Cake": "野菜ケーキ",
    "Basic Kibble": "ベーシックキブル",
    "Simple Kibble": "シンプルキブル",
    "Regular Kibble": "レギュラーキブル",
    "Superior Kibble": "スーペリアキブル",
    "Exceptional Kibble": "エクセプショナルキブル",
    "Extraordinary Kibble": "エクストラオーディナリーキブル",
    "Basic Augmented Kibble": "強化ベーシックキブル",
    "Simple Augmented Kibble": "強化シンプルキブル",
    "Regular Augmented Kibble": "強化レギュラーキブル",
    "Superior Augmented Kibble": "強化スーペリアキブル",
    "Exceptional Augmented Kibble": "強化エクセプショナルキブル",
    "Extraordinary Augmented Kibble": "強化エクストラオーディナリーキブル",
    "Rare Mushroom": "レアキノコ",
    "Rare Flower": "レアフラワー",
    "Giant Bee Honey": "ハチミツ",
    "Bio Toxin": "バイオトキシン",
    "Narcotic": "麻酔薬",
    "Narcoberry": "ナルコベリー",
}


# tamingFoodData は元の種族しか載っていないが、変種は食性が同じなので
# 接頭辞をはがして元の種族のデータを借りる。
VARIANT_PREFIXES = (
    "Aberrant ", "Tek ", "X-", "R-", "Enraged ", "Malfunctioned ", "Eerie ",
    "Bionic ", "Elder ", "Astral ", "Summoned ", "Ascended ", "Zombie ",
    "Skeletal ", "Bone ", "Party ", "Retrieve ", "Ghost ", "Aggressive ",
    "Gamma ", "Beta ", "Alpha ",
)
# 名前の付け方が違うものだけ手当て
VARIANT_ALIASES = {
    "T-Rex": "Rex",
    "Therizinosaurus": "Therizinosaur",
    "Direwolf": "Direwolf",
}


def base_species_name(name, known):
    """変種なら元の種族名を返す。分からなければ None。"""
    n = name
    for _ in range(3):          # 「Aberrant X-Rex」のような重ねがけに備える
        cut = None
        for p in VARIANT_PREFIXES:
            if n.startswith(p) and len(n) > len(p):
                cut = n[len(p):].strip()
                break
        if cut is None:
            break
        n = cut
        if n in known:
            return n
        alias = VARIANT_ALIASES.get(n)
        if alias and alias in known:
            return alias
    alias = VARIANT_ALIASES.get(n)
    if alias and alias in known:
        return alias
    return None


def load(path):
    with io.open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def merged_species(ase_path, asa_path):
    base = load(ase_path)
    over = load(asa_path)
    m, order = {}, []
    for s in base["species"]:
        bp = s.get("blueprintPath")
        if bp:
            m[bp] = dict(s)
            order.append(bp)
    for s in over["species"]:
        bp = s.get("blueprintPath")
        if not bp:
            continue
        if bp in m:
            m[bp].update(s)
        else:
            m[bp] = dict(s)
            order.append(bp)
    return [(bp, m[bp]) for bp in order], base.get("version"), over.get("version")


def main():
    ase = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ASE
    asa = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ASA
    foodp = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_FOOD

    species, ver_ase, ver_asa = merged_species(ase, asa)
    fooddata = load(foodp)
    table = fooddata["tamingFoodData"]
    default_food = {k: v for k, v
                    in (table.get("default", {}).get("specialFoodValues") or {}).items()
                    if k not in ASE_ONLY_FOODS}

    out = {}
    for bp, s in species:
        name = s.get("name")
        tam = s.get("taming")
        if not name or not tam:
            continue
        if any(p in name for p in SKIP_NAME_PARTS) or any(p in bp for p in SKIP_BP_PARTS):
            continue
        if not (tam.get("affinityNeeded0") and tam.get("foodConsumptionBase")):
            continue           # 計算のもとが無い
        if name in out:
            continue           # 同名は先勝ち
        # tamingFoodData に無い恐竜は、まず変種として元の種族から借りる。
        # それでも無ければ「未確認」として共通の食料テーブルから選ばせる。
        entry = table.get(name)
        borrowed = ""
        if not (entry and entry.get("eats")):
            src = base_species_name(name, table)
            if src:
                entry = table[src]
                borrowed = src
            else:
                entry = entry or {}

        stats = s.get("fullStatsRaw") or []
        torpor = stats[STAT_TORPIDITY] if len(stats) > STAT_TORPIDITY else None
        out[name] = {
            "affinity0": tam.get("affinityNeeded0") or 0,
            "affinityPL": tam.get("affinityIncreasePL") or 0,
            "ineff": tam.get("tamingIneffectiveness") or 0,
            "foodBase": tam.get("foodConsumptionBase") or 0,
            "foodMult": tam.get("foodConsumptionMult") or 0,
            "nonViolent": bool(tam.get("nonViolent")),
            "violent": bool(tam.get("violent")),
            "wakeAff": tam.get("wakeAffinityMult") or 1.0,
            "wakeFood": tam.get("wakeFoodDeplMult") or 1.0,
            "torporPS0": tam.get("torporDepletionPS0") or 0,
            "torporBase": (torpor[0] if torpor else 0),
            "torporInc": (torpor[1] if torpor else 0),
            "eats": [x for x in (entry.get("eats") or [])
                     if x not in ASE_ONLY_FOODS],
            "food": {k: v for k, v in (entry.get("specialFoodValues") or {}).items()
                     if k not in ASE_ONLY_FOODS},
            # 食べ物のデータが確認済みか（False なら共通の値で概算）
            "confirmed": bool(entry.get("eats")),
            # 変種として別の種族から借りた場合、その元の名前
            "food_from": borrowed,
        }

    data = {
        "source": {
            "ase_values_version": ver_ase,
            "asa_values_version": ver_asa,
            "taming_food_version": fooddata.get("version"),
            "generator": "tools/build_taming_db.py",
        },
        "default_food": default_food,
        "food_jp": FOOD_JP,
        "species": out,
    }
    dst = os.path.join(PROJ, "data", "taming.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with io.open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("wrote %s (%d種 / 共通食料 %d種)" % (dst, len(out), len(default_food)))

    n_tor = sum(1 for v in out.values() if v["torporPS0"] > 0)
    n_conf = sum(1 for v in out.values() if v["confirmed"] and not v["food_from"])
    n_borrow = sum(1 for v in out.values() if v["food_from"])
    n_none = len(out) - n_conf - n_borrow
    print("  食べ物データ: 直接 %d / 変種として借用 %d / 不明 %d"
          % (n_conf, n_borrow, n_none))
    print("  気絶値の減りが分かる: %d / %d" % (n_tor, len(out)))
    for n in ("Rex", "Carcharodontosaurus", "Argentavis", "Giganotosaurus"):
        v = out.get(n)
        if v:
            print("  %-22s 食べ物%s 気絶減り=%s" % (
                n, "確認済" if v["confirmed"] else "未確認",
                v["torporPS0"] or "不明"))


if __name__ == "__main__":
    main()
