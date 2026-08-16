# -*- coding: utf-8 -*-
"""ARKStatsExtractor の values.json / ASA-values.json から交配データを抽出して
ark-breeding-timer 用の data/species.json を生成する。

  base : values.json        (ASE ベース、全種族)
  over : ASA-values.json    (ASA の追加・上書き。blueprintPath でマージ)

出力形式:
{
  "source": {...},
  "species": [
     {"name": "Rex", "jp": "レックス", "incubation": 17998.56, "gestation": 0,
      "maturation": 333333.33, "cd_min": 64800, "cd_max": 172800}
  ]
}
時間はすべて 1倍(バニラ)の秒数。
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)

# ARKStatsExtractor のリポジトリ or インストール先を指定する。
#   python tools/build_species_db.py <values.json> <ASA-values.json>
# 引数を省いたときは、このプロジェクトの隣に ARKStatsExtractor がある前提で探す。
_REL = os.path.join(os.path.dirname(PROJ), "ARKStatsExtractor",
                    "ARKBreedingStats", "json", "values")
DEFAULT_ASE = os.path.join(_REL, "values.json")
DEFAULT_ASA = os.path.join(_REL, "ASA-values.json")

# 日本語の通称（検索用）。ここに無い種族は英語名で検索する。
JP_NAMES = {
    "Rex": "レックス ティラノ",
    "Giganotosaurus": "ギガノトサウルス ギガ",
    "Carcharodontosaurus": "カルカロドントサウルス カルカロ",
    "Allosaurus": "アロサウルス アロ",
    "Spino": "スピノサウルス スピノ",
    "Yutyrannus": "ユウティラヌス ユティ",
    "Therizinosaur": "テリジノサウルス テリジノ",
    "Baryonyx": "バリオニクス バリオ",
    "Carnotaurus": "カルノタウルス カルノ",
    "Raptor": "ラプトル",
    "Deinonychus": "デイノニクス デイノ",
    "Megalosaurus": "メガロサウルス メガロ",
    "Acrocanthosaurus": "アクロカントサウルス アクロ",
    "Dilophosaur": "ディロフォサウルス ディロ",
    "Compy": "コンピー",
    "Troodon": "トロオドン",
    "Pachy": "パキケファロサウルス パキケ",
    "Pachyrhinosaurus": "パキリノサウルス パキリノ",
    "Triceratops": "トリケラトプス トリケラ",
    "Stegosaurus": "ステゴサウルス ステゴ",
    "Ankylosaurus": "アンキロサウルス アンキロ",
    "Doedicurus": "ドエディクルス ドエディ",
    "Diplodocus": "ディプロドクス ディプロ",
    "Brontosaurus": "ブロントサウルス ブロント",
    "Paraceratherium": "パラケラテリウム パラケラ",
    "Mammoth": "マンモス",
    "Woolly Rhino": "ウーリーライノ サイ",
    "Castoroides": "カストロイデス ビーバー",
    "Megatherium": "メガテリウム ナマケモノ",
    "Chalicotherium": "カリコテリウム カリコ",
    "Daeodon": "ダエオドン",
    "Direwolf": "ダイアウルフ",
    "Dire Bear": "ダイアベア クマ",
    "Thylacoleo": "ティラコレオ",
    "Sabertooth": "サーベルタイガー サーベル",
    "Hyaenodon": "ハイエノドン",
    "Procoptodon": "プロコプトドン カンガルー",
    "Equus": "エクウス 馬 ウマ",
    "Megaloceros": "メガロケロス シカ",
    "Ovis": "オヴィス 羊 ヒツジ",
    "Moschops": "モスコプス",
    "Gallimimus": "ガリミムス ガリ",
    "Iguanodon": "イグアノドン イグア",
    "Parasaur": "パラサウロロフス パラサウル",
    "Phiomia": "フィオミア",
    "Dodo": "ドードー",
    "Lystrosaurus": "リストロサウルス リストロ",
    "Argentavis": "アルゲンタヴィス アルゲン",
    "Pteranodon": "プテラノドン プテラ",
    "Quetzal": "ケツァルコアトルス ケツァル",
    "Tapejara": "タペヤラ",
    "Tropeognathus": "トロペオグナトゥス トロペ",
    "Pelagornis": "ペラゴルニス ペラゴ",
    "Ichthyornis": "イクチオルニス",
    "Dimorphodon": "ディモルフォドン ディモルフ",
    "Terror Bird": "テラーバード",
    "Kairuku": "カイルク ペンギン",
    "Vulture": "ハゲワシ ハゲタカ",
    "Snow Owl": "スノーオウル フクロウ",
    "Griffin": "グリフィン",
    "Managarmr": "マナガルム",
    "Velonasaur": "ヴェロナサウルス ヴェロナ",
    "Rock Drake": "ロックドレイク ドレイク",
    "Basilisk": "バジリスク",
    "Ravager": "ラヴェジャー",
    "Roll Rat": "ロールラット",
    "Karkinos": "カルキノス カニ",
    "Arthropluera": "アースロプレウラ ムカデ",
    "Araneo": "アラネオ クモ",
    "Pulmonoscorpius": "サソリ スコーピオン",
    "Sarco": "サルコスクス サルコ ワニ",
    "Kaprosuchus": "カプロスクス カプロ",
    "Beelzebufo": "ベールゼブフォ カエル",
    "Diplocaulus": "ディプロカウルス",
    "Megalania": "メガラニア",
    "Thorny Dragon": "ソーニードラゴン トゲトカゲ",
    "Basilosaurus": "バシロサウルス バシロ",
    "Megalodon": "メガロドン サメ",
    "Mosasaurus": "モササウルス モササ",
    "Plesiosaur": "プレシオサウルス プレシオ",
    "Dunkleosteus": "ダンクルオステウス ダンクル",
    "Tusoteuthis": "ツソテウティス イカ",
    "Manta": "マンタ エイ",
    "Anglerfish": "アングラー チョウチンアンコウ",
    "Ichthyosaurus": "イクチオサウルス イルカ",
    "Otter": "カワウソ オッター",
    "Magmasaur": "マグマサウル マグマ",
    "Shadowmane": "シャドウメイン シャドメ",
    "Andrewsarchus": "アンドリューサルクス アンドリュー",
    "Desmodus": "デスモダス コウモリ",
    "Fjordhawk": "フィヨルドホーク フィヨルド",
    "Sinomacrops": "シノマクロプス シノマ",
    "Dinopithecus": "ディノピテクス サル",
    "Amargasaurus": "アマルガサウルス アマルガ",
    "Pyromane": "パイロメイン",
    "Xiphactinus": "シファクティヌス",
    "Ceratosaurus": "ケラトサウルス ケラト",
    "Gigantoraptor": "ギガントラプトル ギガラプ",
    "Fasolasuchus": "ファソラスクス",
    "Cosmo": "コスモ",
    "Maewing": "メイウィング メイ",
    "Deinosuchus": "デイノスクス",
    "Oviraptor": "オヴィラプトル",
    "Microraptor": "ミクロラプトル",
    "Pegomastax": "ペゴマスタクス",
    "Hesperornis": "ヘスペロルニス",
    "Dimetrodon": "ディメトロドン",
    "Kentrosaurus": "ケントロサウルス",
    "Carbonemys": "カルボネミス カメ",
    "Doedicurus": "ドエディクルス ドエディ",
    "Megalosaurus": "メガロサウルス",
    "Titanosaur": "ティタノサウルス",
    "Rock Elemental": "ロックエレメンタル ゴーレム",
    "Bulbdog": "バルブドッグ",
    "Featherlight": "フェザーライト",
    "Glowtail": "グロウテイル",
    "Shinehorn": "シャインホーン",
    "Gasbags": "ガスバッグ",
    "Gacha": "ガチャ",
    "Enforcer": "エンフォーサー",
    "Scout": "スカウト",
    "Mek": "メック",
    "Tropeognathus": "トロペオグナトゥス トロペ",
    "Dinopithecus": "ディノピテクス サル",
    "Maewing": "メイウィング メイ",
    "Shadowmane": "シャドウメイン シャドメ",
    "Noglin": "ノグリン",
    "Stryder": "ストライダー",
    "Voidwyrm": "ボイドワイバーン",
    "Astrocetus": "アストロケタス クジラ",
    "Ferox": "フェロックス",
    "Bloodstalker": "ブラッドストーカー",
    "Crystal Wyvern": "クリスタルワイバーン",
    "Fire Wyvern": "ファイアワイバーン",
    "Lightning Wyvern": "ライトニングワイバーン",
    "Poison Wyvern": "ポイズンワイバーン",
    "Ice Wyvern": "アイスワイバーン",
    "Reaper King": "リーパーキング",
    "Karkinos": "カルキノス カニ",
    "Mantis": "マンティス カマキリ",
    "Purlovia": "プルロヴィア",
    "Achatina": "アカティナ カタツムリ",
    "Jerboa": "ジェルボア",
    "Otter": "カワウソ オッター",
    "Dung Beetle": "フンコロガシ",
    "Titanomyrma": "アリ",
    "Onyc": "オニク コウモリ",
    "Meganeura": "メガネウラ トンボ",
    "Trilobite": "三葉虫",
    "Coelacanth": "シーラカンス",
    "Piranha": "ピラニア",
    "Salmon": "サーモン 鮭",
    "Eurypterid": "ウミサソリ",
    "Ammonite": "アンモナイト",
    "Cnidaria": "クラゲ",
    "Electrophorus": "電気ウナギ",
    "Leedsichthys": "リードシクティス",
    "Liopleurodon": "リオプレウロドン",
    "Sarcosuchus": "サルコスクス",
}


# ボス/ミッション/イベント専用の非交配エンティティ。実データ上は交配値を持つが
# 実際には繁殖できないので候補から外す。
SKIP_BP_PARTS = ("/Missions/", "TekCave", "/Gauntlet", "/Boss/")
SKIP_NAME_PARTS = ("VR ", "Ghost", "Corrupted", "Malfunctioned", "Alpha ", "Brute ", "Dinotar")


def load(path):
    with io.open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def main():
    ase_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ASE
    asa_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ASA

    base = load(ase_path)
    over = load(asa_path)

    merged = {}
    order = []
    for s in base["species"]:
        bp = s.get("blueprintPath")
        if not bp:
            continue
        merged[bp] = dict(s)
        order.append(bp)
    for s in over["species"]:
        bp = s.get("blueprintPath")
        if not bp:
            continue
        if bp in merged:
            merged[bp].update(s)
        else:
            merged[bp] = dict(s)
            order.append(bp)

    out = {}
    for bp in order:
        s = merged[bp]
        name = s.get("name")
        br = s.get("breeding")
        if not name or not br:
            continue
        mat = float(br.get("maturationTime") or 0)
        if mat <= 0:
            continue  # 交配不可
        if any(p in bp for p in SKIP_BP_PARTS) or any(p in name for p in SKIP_NAME_PARTS):
            continue
        rec = {
            "name": name,
            "incubation": round(float(br.get("incubationTime") or 0), 3),
            "gestation": round(float(br.get("gestationTime") or 0), 3),
            "maturation": round(mat, 3),
            "cd_min": float(br.get("matingCooldownMin") or 0),
            "cd_max": float(br.get("matingCooldownMax") or 0),
        }
        prev = out.get(name)
        if prev is None:
            out[name] = rec
        elif prev != rec:
            # 同名で値違い(変種)は最初のものを採用。差分だけ報告。
            print("  ! 同名で値が違う(先勝ち): %s" % name)

    species = []
    for name in sorted(out, key=lambda n: n.lower()):
        rec = out[name]
        jp = JP_NAMES.get(name, "")
        if jp:
            rec["jp"] = jp
        species.append(rec)

    data = {
        "source": {
            "ase_values_version": base.get("version"),
            "asa_values_version": over.get("version"),
            "generator": "tools/build_species_db.py",
        },
        "species": species,
    }
    dst = os.path.join(PROJ, "data", "species.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with io.open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("wrote %s (%d species)" % (dst, len(species)))

    # 検算表示
    for n in ("Rex", "Pyromane", "Giganotosaurus", "Dodo"):
        r = out.get(n)
        if r:
            print("  %-18s inc=%9.1f ges=%9.1f mat=%10.1f" % (n, r["incubation"], r["gestation"], r["maturation"]))
    missing = [k for k in JP_NAMES if k not in out]
    if missing:
        print("  (JP名の英語キーが見つからない: %s)" % ", ".join(sorted(missing)))


if __name__ == "__main__":
    main()
