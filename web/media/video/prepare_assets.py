"""영상에 쓸 서류 이미지와 데이터(JSON)를 합성 데이터에서 뽑는다.

- 데모 세트(SET-011)의 서류 4종과 정정본을 PNG로 렌더링하고,
  주요 값의 실제 위치(바운딩 박스)를 PDF에서 찾아 영상의 하이라이트 좌표로 쓴다.
- 검증 결과는 data/generator/check_generated_data.py 의 규칙을 실제로 돌린 값이다.
- 현황 조회 장면은 data/logistics/shipments_seed.json 을 그대로 쓴다.

실행:  python web/media/video/prepare_assets.py   (data/ 는 같은 web/media 아래의 data/)
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "data" / "generator"
sys.path.insert(0, str(GEN))
from check_generated_data import run_rules  # noqa: E402
from generate_documents import corrected_fields, iso6346_check_digit  # noqa: E402

SET_ID = "SET-011"
SET_DIR = ROOT / "data" / "output" / "sets" / SET_ID
PUB = Path(__file__).resolve().parent / "public" / "docs"
SRC = Path(__file__).resolve().parent / "src"
DPI = 144
DOCS = {"bl": "bl.pdf", "invoice": "invoice.pdf", "pl": "packing_list.pdf", "co": "certificate_of_origin.pdf"}


def render(pdf: Path, out: Path, finds: dict[str, str]) -> dict:
    doc = pymupdf.open(pdf)
    page = doc[0]
    zoom = DPI / 72
    pix = page.get_pixmap(dpi=DPI)
    pix.save(out)
    boxes = {}
    for key, text in finds.items():
        hits = page.search_for(text)
        if hits:
            r = hits[-1] if key.endswith("_last") else hits[0]
            boxes[key.removesuffix("_last")] = [round(r.x0 * zoom), round(r.y0 * zoom),
                                                round(r.x1 * zoom), round(r.y1 * zoom)]
    doc.close()
    return {"file": f"docs/{out.name}", "w": pix.width, "h": pix.height, "boxes": boxes}


def main():
    PUB.mkdir(parents=True, exist_ok=True)
    t = json.loads((SET_DIR / "ground_truth.json").read_text(encoding="utf-8"))
    s, p = t["shipment_truth"], t["printed_fields"]
    bl, ci, pl, co = (p["bill_of_lading"], p["commercial_invoice"], p["packing_list"],
                      p["certificate_of_origin"])

    def num(v, d=2):
        return f"{v:,.{d}f}"

    finds = {
        "bl": {"bl_no": bl["bl_no"], "shipper": bl["shipper_name"], "gross": num(bl["gross_weight_kg"]),
               "container": bl["container_numbers"][0], "packages": f"{bl['total_packages']:,} "},
        "invoice": {"invoice_no": ci["invoice_no"], "total": num(ci["total_amount"]),
                    "item": ci["line_items"][0]["description"]},
        "pl": {"invoice_ref": pl["invoice_no_ref"], "gross_total_last": num(pl["total_gross_weight_kg"]),
               "gross_line": num(pl["line_items"][0]["gross_weight_kg"])},
        "co": {"origin": "Country of origin", "hs": "8507.60"},
    }
    images = {}
    for key, fname in DOCS.items():
        images[key] = render(SET_DIR / fname, PUB / f"{key}.png", finds[key])
        images[key + "_fixed"] = render(SET_DIR / "corrected" / fname, PUB / f"{key}_fixed.png", {})
    shutil.copy(SET_DIR / "scans" / "packing_list.jpg", PUB / "scan_pl.jpg")
    shutil.copy(SET_DIR / "scans" / "bl.jpg", PUB / "scan_bl.jpg")

    printed_cn = bl["container_numbers"][0]
    correct_cn = s["containers"][0]["container_no"]
    findings = sorted(run_rules(p))
    fixed_findings = sorted(run_rules(corrected_fields(s)))

    seed = json.loads((ROOT / "data" / "logistics" / "shipments_seed.json").read_text(encoding="utf-8"))
    rows = seed["shipments"]
    delayed = [{"id": r["shipment_id"], "consignee": r["consignee"], "status": r["customs_status"],
                "reason": r["delay_reason"], "free_time_end": r["free_time_end"], "bl_no": r["bl_no"]}
               for r in rows if r["is_delayed"]]
    demo_row = next(r for r in rows if r["set_id"] == SET_ID)

    data = {
        "setId": SET_ID,
        "images": images,
        "shipment": {
            "shipper": s["shipper"]["name"], "consignee": s["buyer"]["name"], "blNo": bl["bl_no"],
            "carrier": s["carrier"], "onBoard": s["on_board_date"],
            "vessel": f"{s['vessel']} / {s['voyage']}", "pol": s["port_of_loading"]["name"],
            "pod": s["port_of_discharge"]["name"], "invoiceNo": ci["invoice_no"],
            "item": s["items"][0]["description"], "quantity": s["items"][0]["quantity"],
            "unit": s["items"][0]["unit"], "packages": s["totals"]["packages"],
            "incoterms": f"{ci['incoterms']} {ci['incoterms_place']}", "currency": ci["currency"],
            "totalAmount": ci["total_amount"], "origin": ci["country_of_origin"],
            "hs6": s["items"][0]["hs6_expected"],
        },
        "checks": {
            "blGross": bl["gross_weight_kg"], "plGrossPrinted": pl["total_gross_weight_kg"],
            "plGrossLineSum": round(sum(li["gross_weight_kg"] for li in pl["line_items"]), 2),
            "containerPrinted": printed_cn, "containerCorrect": correct_cn,
            "checkDigitComputed": iso6346_check_digit(printed_cn[:10]), "checkDigitPrinted": int(printed_cn[10]),
            "findings": findings, "fixedFindings": fixed_findings,
            "injected": t["injected_errors"],
        },
        "logistics": {
            "baseDate": seed["meta"]["base_date"], "weekStart": seed["meta"]["week_start"],
            "weekEnd": seed["meta"]["week_end"], "delayed": delayed,
            "freeTimeSoon": seed["meta"]["free_time_ending_within_2_days_not_cleared"],
            "demo": {"id": demo_row["shipment_id"], "eta": demo_row["eta"], "status": demo_row["customs_status"],
                     "docs": demo_row["docs_status"]},
            "total": seed["meta"]["count"],
        },
    }
    SRC.mkdir(parents=True, exist_ok=True)
    (SRC / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v["boxes"] for k, v in images.items() if v["boxes"]}, indent=1))
    print("findings:", findings, "| fixed:", fixed_findings)
    print("check digit:", printed_cn, "computed", data["checks"]["checkDigitComputed"])
    print("delayed:", len(delayed), "freeTimeSoon:", data["logistics"]["freeTimeSoon"])


if __name__ == "__main__":
    main()
