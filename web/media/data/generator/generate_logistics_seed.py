"""가상 물류 시스템(WMS/TMS/ERP 대용) 화물 데이터를 만든다.

- 샘플 서류 15세트와 같은 B/L 번호를 쓰는 화물 15건 + 배경 화물 15건 = 30건
- 날짜는 --base-date(기본: 오늘) 기준 상대값이다. 발표 당일에 다시 실행하면
  "이번 주 통관 지연 건" 질의에 항상 결과가 나온다.
- 데모 세트(기본 SET-011)는 "입항 3일 전, 서류 검증 필요" 상태다.
- 나머지 오류 세트(SET-012~015)는 해당 오류를 지연 사유로 가진 지연 화물이 된다.
- 하선일, 프리타임 만료일, 반출일을 넣어 "프리타임이 끝나가는데 아직 수리 안 된 화물" 질의를 받을 수 있다.
  프리타임 일수는 가상 값이다 (실제 값은 터미널·선사 요율표를 따른다).

먼저 generate_documents.py 를 실행해 output/sets 가 있어야 한다.
실행:  python data/generator/generate_logistics_seed.py [--base-date 2026-11-21]
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from catalog import BUYERS, CARRIERS, PORTS, SUPPLIERS

ROOT = Path(__file__).resolve().parents[1]
SETS = ROOT / "output" / "sets"
OUT = ROOT / "logistics"

STAFF = ["김하늘", "이준서", "박서윤", "최도윤", "정민지"]
WAREHOUSES = ["부산신항 보세창고 A동", "부산신항 보세창고 B동", "북항 CY 3번", "감천항 냉동 보세창고"]
FREE_TIME_DAYS = 5  # 가상 값

# 오류 종류 → 지연 사유 (사람이 읽는 말)
DELAY_BY_ERROR = {
    "gross_weight_digit_swap": "서류 불일치: B/L과 Packing List의 총중량이 다름",
    "package_count_mismatch": "서류 불일치: B/L 포장 수가 Packing List와 다름",
    "container_check_digit": "서류 오류: 컨테이너 번호 체크디지트 불일치",
    "invoice_total_mismatch": "서류 오류: Invoice 합계 금액이 품목 합계와 다름",
    "invoice_ref_typo": "서류 불일치: Packing List의 Invoice 번호가 다름",
    "origin_mismatch": "보완 요구: 원산지증명서 원산지가 Invoice와 다름",
    "missing_customs_value_info": "보완 요구: FOB 조건 운임·보험료 자료 미제출",
}

BACKGROUND_DELAYS = [
    ("검사 지정", "세관 물품검사 지정"),
    ("심사 중", "요건 확인 대기 (식품 검사)"),
]


def at(d: date, hour: int) -> str:
    return datetime.combine(d, time(hour, 0)).isoformat(timespec="minutes")


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-date", default=date.today().isoformat())
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--demo-set", default="SET-011", help="입항 3일 전 데모에 쓸 세트")
    args = ap.parse_args()
    today = date.fromisoformat(args.base_date)
    week_start = today - timedelta(days=today.weekday())
    rng = random.Random(args.seed)

    truths = [json.loads((p / "ground_truth.json").read_text(encoding="utf-8"))
              for p in sorted(SETS.iterdir()) if (p / "ground_truth.json").exists()]
    if not truths:
        raise SystemExit("output/sets 가 비어 있다. generate_documents.py 를 먼저 실행할 것")

    rows = []

    def add(ata: date | None, status: str, **kw):
        kw["shipment_id"] = f"SHP-{today:%y%m}-{len(rows) + 1:03d}"
        kw.setdefault("pod", "KRPUS")
        kw.setdefault("assigned_to", rng.choice(STAFF))
        kw.setdefault("warehouse", rng.choice(WAREHOUSES[:3]))
        kw["ata"] = iso(ata)
        kw["discharge_date"] = iso(ata)
        kw["free_time_days"] = FREE_TIME_DAYS if ata else None
        kw["free_time_end"] = iso(ata + timedelta(days=FREE_TIME_DAYS)) if ata else None
        kw["gate_out_date"] = iso(ata + timedelta(days=rng.randint(2, 4))) if status == "반출 완료" else None
        kw["customs_status"] = status
        rows.append(kw)

    # 1) 샘플 서류와 연결된 화물 15건
    for t in truths:
        s = t["shipment_truth"]
        errors = [e["error_type"] for e in t["injected_errors"]]
        common = dict(
            set_id=t["set_id"], bl_no=s["bl_no"], invoice_no=s["invoice_no"],
            consignee=s["buyer"]["name"], shipper=s["shipper"]["name"],
            cargo_summary=", ".join(l["description"] for l in s["items"]),
            packages=s["totals"]["packages"], gross_weight_kg=s["totals"]["gross_weight_kg"],
            containers=[c["container_no"] for c in s["containers"]],
            pol=s["port_of_loading"]["locode"], vessel=s["vessel"], voyage=s["voyage"],
        )
        if s.get("reefer_temp"):
            common["warehouse"] = "감천항 냉동 보세창고"

        if t["set_id"] == args.demo_set:
            # 데모: 서류는 받았고 배는 3일 뒤 입항. 지금 서류를 고치면 입항 전에 신고할 수 있다
            eta = today + timedelta(days=3)
            add(None, "입항 예정", **common, eta=iso(eta), docs_status="검증 필요 (입항 전)",
                is_delayed=False, delay_reason=None, delay_days=0,
                expected_clearance_date=iso(eta + timedelta(days=1)),
                status_updated_at=at(today, 9))
        elif errors:
            # 이번 주에 입항했는데 서류 문제로 멈춘 화물
            ata = max(week_start, today - timedelta(days=rng.randint(1, 3)))
            status = "보완 요구" if any(e in ("origin_mismatch", "missing_customs_value_info")
                                    for e in errors) else "심사 중"
            expected = ata + timedelta(days=1)
            add(ata, status, **common, eta=iso(ata), docs_status="보완 요청 중",
                is_delayed=True, delay_reason=" / ".join(DELAY_BY_ERROR[e] for e in errors),
                delay_days=max(0, (today - expected).days),
                expected_clearance_date=iso(expected), status_updated_at=at(today, rng.randint(9, 17)))
        else:
            # 정상 화물: 이미 수리·반출됐거나 이번 주·다음 주 입항 예정
            offset = rng.choice([-9, -6, -4, -2, 1, 3, 5])
            ata = today + timedelta(days=offset) if offset < 0 else None
            eta = ata or today + timedelta(days=offset)
            status = "반출 완료" if offset <= -6 else "신고 수리" if offset <= -2 else "입항 예정"
            add(ata, status, **common, eta=iso(eta), docs_status="검증 완료",
                is_delayed=False, delay_reason=None, delay_days=0,
                expected_clearance_date=iso(eta + timedelta(days=2)),
                status_updated_at=at(min(today, eta), rng.randint(9, 17)))

    # 2) 배경 화물 15건 (서류 없음). 이 중 2건은 서류 외 사유로 지연
    sup_keys = list(SUPPLIERS)
    for j in range(15):
        sup = SUPPLIERS[rng.choice(sup_keys)]
        buyer = BUYERS[sup["buyer"]]
        carrier = rng.choice(CARRIERS)
        common = dict(
            set_id=None, bl_no=f"{carrier['key']}{today:%y%m}{rng.randint(100000, 999999)}",
            invoice_no=None, consignee=buyer["name"], shipper=sup["name"],
            cargo_summary="(서류 미등록 배경 화물)", packages=rng.randint(40, 900),
            gross_weight_kg=round(rng.uniform(3000, 21000), 2), containers=[],
            pol=sup["pol"], vessel=rng.choice(carrier["vessels"]),
            voyage=f"{rng.randint(1, 99):03d}{rng.choice('EWNS')}", docs_status="서류 미등록",
        )
        if j < len(BACKGROUND_DELAYS):
            status, reason = BACKGROUND_DELAYS[j]
            ata = max(week_start, today - timedelta(days=2 + j))
            expected = ata + timedelta(days=1)
            add(ata, status, **common, eta=iso(ata), is_delayed=True, delay_reason=reason,
                delay_days=max(0, (today - expected).days), expected_clearance_date=iso(expected),
                status_updated_at=at(today, rng.randint(9, 17)))
        else:
            offset = rng.randint(-12, 7)
            ata = today + timedelta(days=offset) if offset <= 0 else None
            eta = today + timedelta(days=offset)
            status = ("반출 완료" if offset <= -7 else "신고 수리" if offset <= -3
                      else "수입신고" if offset <= 0 else "입항 예정")
            add(ata, status, **common, eta=iso(eta), is_delayed=False, delay_reason=None, delay_days=0,
                expected_clearance_date=iso(eta + timedelta(days=2)),
                status_updated_at=at(min(today, eta), rng.randint(9, 17)))

    not_released = {"반출 완료", "신고 수리"}
    soon = [r for r in rows if r["free_time_end"] and r["customs_status"] not in not_released
            and date.fromisoformat(r["free_time_end"]) <= today + timedelta(days=2)]

    OUT.mkdir(exist_ok=True)
    meta = {"base_date": today.isoformat(), "week_start": week_start.isoformat(),
            "week_end": (week_start + timedelta(days=6)).isoformat(),
            "pod_name": PORTS["KRPUS"], "count": len(rows),
            "delayed_count": sum(r["is_delayed"] for r in rows),
            "demo_set": args.demo_set,
            "free_time_ending_within_2_days_not_cleared": len(soon),
            "free_time_note": f"프리타임 {FREE_TIME_DAYS}일은 가상 값"}
    (OUT / "shipments_seed.json").write_text(
        json.dumps({"meta": meta, "shipments": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"화물 {len(rows)}건 (지연 {meta['delayed_count']}건, 프리타임 2일 이내 만료·미수리 {len(soon)}건), "
          f"기준일 {today}, 데모 {args.demo_set} → {OUT / 'shipments_seed.json'}")


if __name__ == "__main__":
    main()
