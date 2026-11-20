"""생성된 데이터가 의도대로 만들어졌는지 확인한다.

기획서 4장의 교차 검증 규칙을 인쇄값(printed_fields)에 그대로 돌려서,
- 정상 세트에서는 오류가 하나도 안 나오고
- 오류 세트에서는 넣은 오류(expected_findings)가 정확히 나오는지 본다.
F2 검증 도구를 만들 때 기준 구현으로 참고해도 된다.

실행:  python data/generator/check_generated_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from generate_documents import corrected_fields, iso6346_check_digit

ROOT = Path(__file__).resolve().parents[1]
SETS = ROOT / "output" / "sets"
NO_FREIGHT_TERMS = {"EXW", "FCA", "FAS", "FOB"}


def run_rules(p: dict) -> set[tuple[str, str]]:
    bl, ci, pl, co = (p["bill_of_lading"], p["commercial_invoice"], p["packing_list"],
                      p["certificate_of_origin"])
    found = set()
    if abs(bl["gross_weight_kg"] - pl["total_gross_weight_kg"]) > 0.5:
        found.add(("gross_weight_match", "error"))
    if bl["total_packages"] != pl["total_packages"]:
        found.add(("package_count_match", "error"))
    for cn in bl["container_numbers"]:
        if len(cn) != 11 or iso6346_check_digit(cn[:10]) != int(cn[10]):
            found.add(("container_check_digit", "error"))
    if abs(sum(li["amount"] for li in ci["line_items"]) - ci["total_amount"]) > 0.01:
        found.add(("invoice_amount_sum", "error"))
    if pl["invoice_no_ref"] != ci["invoice_no"] or co["invoice_no_ref"] != ci["invoice_no"]:
        found.add(("invoice_reference_match", "error"))
    if ci["country_of_origin"] != co["country_of_origin"]:
        found.add(("origin_match", "error"))
    if ci["incoterms"] in NO_FREIGHT_TERMS and (ci["freight_amount"] is None or ci["insurance_amount"] is None):
        found.add(("customs_value_info", "missing_warning"))
    if abs(sum(li["gross_weight_kg"] for li in pl["line_items"]) - pl["total_gross_weight_kg"]) > 0.5:
        found.add(("pl_gross_weight_sum", "error"))
    if sum(li["quantity"] for li in pl["line_items"]) != sum(li["quantity"] for li in ci["line_items"]):
        found.add(("item_quantity_match", "error"))
    return found


def main():
    ok = True
    for d in sorted(SETS.iterdir()):
        t = json.loads((d / "ground_truth.json").read_text(encoding="utf-8"))
        got = run_rules(t["printed_fields"])
        want = {(f["rule"], f["severity"]) for f in t["expected_findings"]
                if f["severity"] in ("error", "missing_warning")}
        # 오류 세트의 정정본(corrected/)은 아무 오류도 나오면 안 된다
        clean_ok = True
        if t.get("corrected_files"):
            clean_ok = not run_rules(corrected_fields(t["shipment_truth"]))
            clean_ok &= all((d / f).exists() for f in t["corrected_files"].values())
        passed = got == want and clean_ok
        ok &= passed
        print(f"{'OK ' if passed else 'BAD'} {t['set_id']} {t['scenario']:6} "
              f"expected={sorted(r for r, _ in want)} got={sorted(r for r, _ in got)}"
              + ("  정정본=통과" if t.get("corrected_files") and clean_ok else ""))
    print("\n모든 세트가 의도대로 생성됨" if ok else "\n의도와 다른 세트가 있음")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
