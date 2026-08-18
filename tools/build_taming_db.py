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
sys.path.insert(0, HERE)
from build_species_db import JP_NAMES  # noqa: E402  恐竜の日本語名を借りる
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

# 食べ物の日本語名。ゲーム内の表記に合わせてある
# （出どころ: ark.wiki.gg 日本語版 と wikiwiki.jp の ASA 版。2026-08-18 確認）
FOOD_JP = {
    # 肉
    "Raw Meat": "生肉",
    "Cooked Meat": "こんがり肉",
    "Cooked Meat Jerky": "干し肉",
    "Raw Prime Meat": "霜降り肉",
    "Cooked Prime Meat": "霜降りこんがり肉",
    "Prime Meat Jerky": "霜降り干し肉",
    "Raw Mutton": "羊肉",
    "Cooked Lamb Chop": "ラムチョップ",
    "Spoiled Meat": "腐った肉",
    # 魚
    "Raw Fish Meat": "魚肉",
    "Cooked Fish Meat": "こんがり魚",
    "Raw Prime Fish Meat": "大トロ",
    "Cooked Prime Fish Meat": "こんがり大トロ",
    # キブル（(超級)が Exceptional、(特級)が Extraordinary。逆ではない）
    "Basic Kibble": "キブル(基本)",
    "Simple Kibble": "キブル(簡易)",
    "Regular Kibble": "キブル(通常)",
    "Superior Kibble": "キブル(優)",
    "Exceptional Kibble": "キブル(超級)",
    "Extraordinary Kibble": "キブル(特級)",
    "Basic Augmented Kibble": "増強キブル(基本)",
    "Simple Augmented Kibble": "増強キブル(簡易)",
    "Regular Augmented Kibble": "増強キブル(通常)",
    "Superior Augmented Kibble": "増強キブル(優)",
    "Exceptional Augmented Kibble": "増強キブル(超級)",
    "Extraordinary Augmented Kibble": "増強キブル(特級)",
    # ベリー
    "Berries": "ベリー類",
    "Mejoberry": "メジョベリー",
    "Amarberry": "アマルベリー",
    "Azulberry": "アズールベリー",
    "Tintoberry": "ティントベリー",
    "Narcoberry": "ナルコベリー",
    "Stimberry": "スティムベリー",
    # 作物・料理
    "Vegetables": "野菜",
    "Crops": "作物",
    "Rockarrot": "ニンジン",
    "Longrass": "トウモロコシ",
    "Savoroot": "ジャガイモ",
    "Citronal": "レモン",
    "Sweet Vegetable Cake": "スイートベジタブルケーキ",
    "Giant Bee Honey": "巨大ハチのハチミツ",
    "Broth of Enlightenment": "啓発の煮汁",
    "Beer Jar": "ビール瓶",
    # きのこ・植物
    "Rare Mushroom": "レアマッシュルーム",
    "Rare Flower": "レアフラワー",
    "Aggeravic Mushroom": "アガーラビックマッシュルーム",
    "Aquatic Mushroom": "アクアティックマッシュルーム",
    "Ascerbic Mushroom": "アサービックマッシュルーム",
    "Auric Mushroom": "金のマッシュルーム",
    "Archelon Algae (ASA)": "アーケロンの海藻",
    "Plant Species X Seed": "プラントXの種",
    "Plant Species Y Seed": "プラントYの種",
    "Plant Species Z Seed": "プラントZの種",
    "Plant Species Z Seed (SpeedHack)": "プラントZの種",
    # 素材・その他
    "Black Pearl": "黒真珠",
    "Chitin": "キチン",
    "Keratin": "ケラチン",
    "Clay": "粘土",
    "Stone": "石",
    "Metal": "金属",
    "Sulfur": "硫黄",
    "Element": "エレメント",
    "Element Ore": "エレメント鉱石",
    "Deathworm Horn": "デスワームの角",
    "Woolly Rhino Horn": "ケブカサイの角",
    "Leech Blood": "ヒルの血液",
    "AnglerGel": "アンコウのジェル",
    "Bio Toxin": "バイオトキシン",
    "Narcotic": "麻酔薬",
    "Bug Repellant": "防虫剤",
    "Ammunition": "弾薬",
    "Other Items": "その他のもの",
    # 糞
    "Human Feces": "人間の糞",
    "Small Animal Feces": "小型動物の糞",
    "Medium Animal Feces": "中型動物の糞",
    "Large Animal Feces": "大型動物の糞",
    "Massive Animal Feces": "巨大生物の糞",
    "Snow Owl Pellet": "雪フクロウのペレット",
    # 卵（総称）
    "Dinosaur Egg": "恐竜の卵",
    "Golden Hesperornis Egg": "黄金のヘスペロルニスの卵",
}

# 卵の名前は略称で書かれているので、恐竜の日本語名に橋渡しする
EGG_ALIASES = {
    "Rex": "レックス", "Trike": "トリケラトプス", "Stego": "ステゴサウルス",
    "Bronto": "ブロントサウルス", "Dilo": "ディロフォサウルス",
    "Dimorph": "ディモルフォドン", "Diplo": "ディプロドクス",
    "Lystro": "リストロサウルス", "Therizino": "テリジノサウルス",
    "Pachyrhino": "パキリノサウルス", "Ankylo": "アンキロサウルス",
    "Carno": "カルノタウルス", "Compy": "コンピー", "Turtle": "カルボネミス",
    "Kentro": "ケントロサウルス", "Titanboa": "タイタンボア",
    "Pulminoscorpius": "サソリ", "Moth": "モス", "Camelsaurus": "モルレラトプス",
    "Featherlight": "フェザーライト", "Glowtail": "グロウテイル",
    "Achaeopteryx": "アーケオプテリクス", "Archaeopteryx": "アーケオプテリクス",
    "Hesperornis": "ヘスペロルニス", "Oviraptor": "オヴィラプトル",
    "Pegomastax": "ペゴマスタクス", "Microraptor": "ミクロラプトル",
    "Pachycephalosaurus": "パキケファロサウルス", "Mantis": "マンティス",
    "Dimetrodon": "ディメトロドン",
    "Vulture": "ハゲワシ", "Wyvern": "ワイバーン", "Basilisk": "バジリスク",
    "Rock Drake": "ロックドレイク", "Snow Owl": "スノーオウル",
    "Velonasaur": "ヴェロナサウルス", "Terror Bird": "テラーバード",
    "Thorny Dragon": "ソーニードラゴン", "Giganotosaurus": "ギガノトサウルス",
}


def _dino_jp(word):
    """卵の名前に出てくる恐竜名を日本語にする。分からなければ None。"""
    if word in EGG_ALIASES:
        return EGG_ALIASES[word]
    jp = JP_NAMES.get(word)
    if jp:
        return jp.split(" ")[0]
    return None


def jp_food_name(name):
    """食べ物の日本語名。表にあればそれ、卵なら組み立て、駄目なら None。"""
    if name in FOOD_JP:
        return FOOD_JP[name]
    if name.endswith(" Egg"):
        body = name[:-4]
        fert = body.startswith("Fertilized ")
        if fert:
            body = body[len("Fertilized "):]
        aberrant = body.startswith("Aberrant ")
        if aberrant:
            body = body[len("Aberrant "):]
        tek = body.startswith("Tek ")
        if tek:
            body = body[len("Tek "):]
        jp = _dino_jp(body)
        if not jp:
            return None
        return "%s%s%sの%s" % ("アベレーション " if aberrant else "",
                               "テック" if tek else "", jp,
                               "受精卵" if fert else "卵")
    return None


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

    # 出てくる食べ物すべてに日本語名を用意する（卵は自動で組み立てる）
    all_foods = set(default_food)
    for v in out.values():
        all_foods |= set(v["eats"]) | set(v["food"])
    food_jp, no_jp = {}, []
    for n in sorted(all_foods):
        jp = jp_food_name(n)
        if jp:
            food_jp[n] = jp
        else:
            no_jp.append(n)

    data = {
        "source": {
            "ase_values_version": ver_ase,
            "asa_values_version": ver_asa,
            "taming_food_version": fooddata.get("version"),
            "generator": "tools/build_taming_db.py",
        },
        "default_food": default_food,
        "food_jp": food_jp,
        "species": out,
    }
    dst = os.path.join(PROJ, "data", "taming.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with io.open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("wrote %s (%d種 / 共通食料 %d種)" % (dst, len(out), len(default_food)))
    print("  食べ物の日本語名: %d / %d" % (len(food_jp), len(all_foods)))
    if no_jp:
        print("  英語のまま: %s" % ", ".join(no_jp[:12]))

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
