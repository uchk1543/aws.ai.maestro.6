"""가상 ERP 품목 마스터와 HS 정답표를 만든다.

- master/item_master.csv  : 가상 ERP에 등록된 품목. 일부 샘플 품목은 일부러 빠져 있다(신규 품목 시연용).
- master/hs_answer_key.csv: 샘플 서류에 나오는 모든 품목의 HS 6단위 정답과 근거. HSK 10단위는 비워 둔다.

실행:  python data/generator/generate_master_data.py
"""
from __future__ import annotations

import csv
from pathlib import Path

from catalog import EXTRA_MASTER_ITEMS, ITEMS

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "master"


def hs_dot(hs6: str | None) -> str:
    return f"{hs6[:4]}.{hs6[4:]}" if hs6 else ""


def main():
    MASTER.mkdir(exist_ok=True)

    master_rows = []
    for it in ITEMS.values():
        if it["in_master"]:
            master_rows.append({
                "item_code": it["code"], "description_en": it["description"], "name_ko": it["name_ko"],
                "material": it["material"], "use": it["use"], "unit": it["unit"],
                "registered_hs6": hs_dot(it["hs6"]), "registered_hsk10": "",
            })
    for it in EXTRA_MASTER_ITEMS:
        master_rows.append({
            "item_code": it["code"], "description_en": it["description"], "name_ko": it["name_ko"],
            "material": it["material"], "use": it["use"], "unit": "PCS",
            "registered_hs6": hs_dot(it["hs6"]), "registered_hsk10": "",
        })
    with open(MASTER / "item_master.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(master_rows[0].keys()))
        w.writeheader()
        w.writerows(master_rows)

    key_rows = []
    for key, it in ITEMS.items():
        key_rows.append({
            "item_key": key, "item_code": it["code"], "description_en": it["description"],
            "name_ko": it["name_ko"], "in_master": "Y" if it["in_master"] else "N",
            "expected_hs6": hs_dot(it["hs6"]), "expected_hsk10": "",
            "ambiguous": "Y" if it["hs6"] is None else "N",
            "declared_on_co": hs_dot(it["hs6"] or it.get("co_hs6")),
            "basis_ko": it["hs_basis"], "clarifying_question_ko": it.get("clarify", ""),
        })
    with open(MASTER / "hs_answer_key.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(key_rows[0].keys()))
        w.writeheader()
        w.writerows(key_rows)

    print(f"품목 마스터 {len(master_rows)}건, HS 정답표 {len(key_rows)}건 → {MASTER}")


if __name__ == "__main__":
    main()
