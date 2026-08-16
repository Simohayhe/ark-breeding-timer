# -*- coding: utf-8 -*-
"""テイムの計算。

ARKStatsExtractor の Taming.cs をそのまま移したもの。式の出どころ:
  affinityNeeded = (affinityNeeded0 + affinityIncreasePL * level)
  foodAffinity   = 食料のaffinity × 個数 × TamingSpeedMultiplier × 4(定数)
  必要な個数     = ceil(affinityNeeded / foodAffinity)
  かかる秒数     = ceil(個数 × 食料のfoodValue
                       / (foodConsumptionBase × foodConsumptionMult × 食料消費倍率))
  テイム効率(TE) = 1 / (1 + tamingIneffectiveness × 個数/foodAffinity)
  ボーナスLv     = floor(level × TE / 2)

気絶値まわり:
  最大気絶値       = 気絶値ベース × (1 + Lvごとの増加 × (level - 1))
  1秒あたりの減り  = (torporPS0 + (level-1)^0.800403041 / (22.39671632 / torporPS0))
                     × 気絶減少倍率
  torporPS0 が無い種族は計算できない（データ側に無い）。
"""
from __future__ import annotations

import io
import json
import math
import os

HARD_CODED_TAMING_MULT = 4    # ARK 側の固定値

# 麻酔アイテム: (表示名, 回復する気絶値, 効き終わるまでの秒数)
NARCOTICS = (
    ("ナルコベリー", 7.5, 3),
    ("アセビックマッシュルーム", 25, 3),
    ("麻酔薬", 40, 8),
    ("バイオトキシン", 80, 16),
)


class TamingDB:
    def __init__(self, path):
        try:
            with io.open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        self.source = data.get("source", {})
        self.default_food = data.get("default_food", {})
        self.food_jp = data.get("food_jp", {})
        self.species = data.get("species", {})

    def names(self):
        return sorted(self.species, key=str.lower)

    def get(self, name):
        return self.species.get(name)

    def food_label(self, name):
        jp = self.food_jp.get(name)
        return "%s（%s）" % (jp, name) if jp else name

    def foods_for(self, sp, include_kibble=False):
        """その種族が食べられるもの。

        食べ物データが無い種族（ASAで追加された恐竜など）には共通テーブルを
        出すが、**キブルは既定で出さない**。どのキブルが好物かが分からないうえ、
        カルカロのようにテイム方法が特殊でキブルを使わない恐竜も多いため、
        並べると嘘の選択肢になってしまう。
        """
        names = list(sp.get("eats") or [])
        if names:
            return [n for n in names if self.food_value(sp, n)]
        names = list(self.default_food)
        if not include_kibble:
            names = [n for n in names if "Kibble" not in n]
        return [n for n in names if self.food_value(sp, n)]

    def food_value(self, sp, name):
        """(foodValue, affinity, quantity) を返す。引けなければ None。"""
        v = (sp.get("food") or {}).get(name)
        if v is None and (not sp.get("eats") or name in (sp.get("eats") or [])):
            v = self.default_food.get(name)
        if v is None:
            return None
        return {"f": float(v.get("f") or 0), "a": float(v.get("a") or 0),
                "q": int(v.get("q") or 1), "u": bool(v.get("u"))}


def torpor_total(sp, level):
    """そのレベルの最大気絶値。"""
    base = float(sp.get("torporBase") or 0)
    inc = float(sp.get("torporInc") or 0)
    if base <= 0:
        return 0.0
    return base * (1 + inc * (level - 1))


def torpor_per_second(sp, level, drain_mult=1.0):
    """1秒あたりに減る気絶値。データが無ければ 0。"""
    t0 = float(sp.get("torporPS0") or 0)
    if t0 <= 0:
        return 0.0
    return (t0 + math.pow(max(0, level - 1), 0.800403041)
            / (22.39671632 / t0)) * drain_mult


def calc(db: TamingDB, sp, level, food_name, mults=None, current_food=0.0):
    """テイムの計算。結果を辞書で返す。

    mults: {"taming": TamingSpeedMultiplier,
            "food_drain": DinoCharacterFoodDrainMultiplier,
            "wild_food_drain": WildDinoCharacterFoodDrainMultiplier,
            "torpor_drain": WildDinoTorporDrainMultiplier}
    current_food: いま相手が持っている食料値。0 より大きいと、それを消費し
                  きるまでの待ち時間を別に出す。
    """
    m = {"taming": 1.0, "food_drain": 1.0, "wild_food_drain": 1.0,
         "torpor_drain": 1.0}
    m.update(mults or {})

    food = db.food_value(sp, food_name)
    if not food:
        return {"ok": False, "why": "その食べ物の値が分かりません"}

    affinity_needed = (float(sp.get("affinity0") or 0)
                       + float(sp.get("affinityPL") or 0) * level)

    food_affinity = food["a"] * food["q"]
    food_value = food["f"]
    if sp.get("nonViolent"):
        food_affinity *= float(sp.get("wakeAff") or 1.0)
        food_value *= float(sp.get("wakeFood") or 1.0)
    food_affinity *= m["taming"] * HARD_CODED_TAMING_MULT

    if food_affinity <= 0 or food_value <= 0:
        return {"ok": False, "why": "その食べ物ではテイムできません"}

    pieces = int(math.ceil(affinity_needed / food_affinity))

    # 1秒あたりに減る食料
    drain = (float(sp.get("foodBase") or 0) * float(sp.get("foodMult") or 0)
             * m["food_drain"] * m["wild_food_drain"])
    if drain <= 0:
        return {"ok": False, "why": "食料の減りかたが分かりません"}
    seconds = int(math.ceil(pieces * food_value / drain))

    # ineff が 0 の種族はデータ側に値が無いだけのことが多く、そのまま計算すると
    # TE が常に100%になってしまう。信用できないので印を付けて返す。
    ineff = float(sp.get("ineff") or 0)
    te = 1.0 / (1 + ineff * (pieces / food_affinity))
    te = max(0.0, min(1.0, te))
    bonus = int(math.floor(level * te / 2))

    # 気絶まわり
    total_torpor = torpor_total(sp, level)
    tps = torpor_per_second(sp, level, m["torpor_drain"])
    torpor_needed = max(0.0, tps * seconds - total_torpor)
    narcotics = []
    if tps > 0:
        for label, heal, dur in NARCOTICS:
            narcotics.append((label, int(math.ceil(torpor_needed / (heal + dur * tps)))
                              if torpor_needed > 0 else 0))
    wake_seconds = int(total_torpor / tps) if tps > 0 else 0

    # いま持っている食料を消費しきるまで（食べ始めるのを待つ時間の目安）
    wait_seconds = int(math.ceil(current_food / drain)) if current_food > 0 else 0

    return {
        "ok": True,
        "pieces": pieces,
        "seconds": seconds,
        "wait_seconds": wait_seconds,
        "total_seconds": seconds + wait_seconds,
        "te": te,
        "te_known": ineff > 0,
        "bonus": bonus,
        "level_after": level + bonus,
        "total_torpor": total_torpor,
        "torpor_per_sec": tps,
        "torpor_needed": torpor_needed,
        "narcotics": narcotics,
        "wake_seconds": wake_seconds,
        "food_drain_per_sec": drain,
        "unconfirmed_food": food.get("u", False) or not sp.get("confirmed"),
        "food_from": sp.get("food_from") or "",
        "violent": bool(sp.get("violent")),
        "non_violent": bool(sp.get("nonViolent")),
    }
