"""데이터셋에 딸린 정답 세 가지를 만든다. 서류는 다시 그리지 않고 CSV만 읽는다 (발표용 서류 잠금이 그대로 남는다).

1. 신고서 정답 eval/declarations.csv (발표용 eval/test/declarations.csv)
   세트마다 신고서 간이 칸의 진짜 값과, 오류 때문에 비워야 하는 칸(expect_blank). 칸 목록은 제안이다(검증 담당 C4 #22가 확정).
2. 가상 화물 기록 samples/data/shipments.json
   현황 조회에 쓰는 Shipment 목록 (docs/examples/shipment.json 형식). data/seed/ 로 옮겨 쓰면 된다 (A5 #8).
3. 현황 조회 질문 eval/queries.csv
   질문 20개, 기대 조건(JSON), 기대 건수. 건수는 2번 화물 기록에서 코드가 센다. 통관 상태 값과 '통관 지연' 기준은
   제안이다(검증 담당 E1 #29가 확정). 기준이 바뀌면 이 파일 맨 위 값만 고치고 다시 돌린다.

사용법 (저장소 맨 위에서)
  uv run --with openpyxl --with reportlab --with pillow --with numpy python samples/make_extra.py
"""
import csv, datetime as dt, json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_samples as kit  # noqa: E402
import generate_dataset as gen  # noqa: E402

ROOT = kit.ROOT
SHIPMENTS = ROOT / "samples/data/shipments.json"
QUERIES = ROOT / "eval/queries.csv"

# ── 현황 조회 제안 (검증 담당 E1이 확정하면 고친다) ────────────────────────────
TODAY = dt.date(2026, 11, 21)                     # 기준일: 발표일(토). 채점은 이 날을 '오늘'로 넘긴다
STATUSES = ["입항", "수입신고", "심사 중", "검사 중", "수리", "반출"]   # customs_status 값
CLEARED = {"수리", "반출"}                         # 통관이 끝난 상태
DELAY_DAYS = 3                                    # 통관 지연: 입항 후 3일이 지나도 수리·반출이 아님
SEED_COUNT = {"earlier": 30, "last_week": 22, "this_week": 24}   # 기준일 주(월~일) 앞뒤로 나눈 건수
CONSIGNEE_KO = {"KR01": "샘플트레이딩코리아", "KR02": "이그잼플유통", "KR03": "한빛샘플",
                "KR04": "샘플푸드코리아", "KR05": "이그잼플홈리빙"}
ITEM_KO = {"STAINLESS STEEL BOLTS": "스테인리스 볼트", "KITCHEN KNIVES": "주방용 칼", "CORDLESS DRILLS": "충전 드릴",
           "ALUMINIUM PROFILES": "알루미늄 프로파일", "LITHIUM-ION BATTERY PACKS": "리튬이온 배터리팩",
           "SOLAR MODULES": "태양광 모듈", "LED PANEL LIGHTS": "LED 평판 조명", "PLASTIC STORAGE BOXES": "플라스틱 수납함",
           "BICYCLE TYRES": "자전거 타이어", "PORCELAIN FLOOR TILES": "자기질 바닥 타일", "PORCELAIN TABLEWARE": "자기 식기",
           "COTTON T-SHIRTS": "면 티셔츠", "COTTON SHIRTS": "면 셔츠", "COTTON TOWELS": "면 수건", "WOODEN CHAIRS": "원목 의자",
           "WOODEN TABLES": "원목 식탁", "SPORTS SHOES": "운동화", "BACKPACKS": "백팩", "FROZEN SHRIMP": "냉동 새우",
           "CASHEW KERNELS": "캐슈너트", "GREEN COFFEE BEANS": "커피 생두", "STAINLESS STEEL SCREWS": "스테인리스 나사",
           "SOLAR CELLS": "태양전지", "MELAMINE TABLEWARE": "멜라민 식기", "RETREADED TYRES": "재생 타이어",
           "CERAMIC WALL TILES": "도기질 벽 타일", "MEN'S SHIRTS": "남성 셔츠"}

# ── 신고서 간이 칸 제안 (검증 담당 C4가 확정하면 고친다) ───────────────────────
# (칸, 이름, 단위: header=신고서 한 장에 하나, line=품목 줄마다)
DECL_FIELDS = [("bl_no", "B/L 번호", "header"), ("vessel", "선기명", "header"), ("importer", "수입자", "header"),
               ("supplier", "해외공급자", "header"), ("export_country", "적출국", "header"),
               ("total_gross_kg", "총중량(kg)", "header"), ("total_packages", "총포장갯수", "header"),
               ("package_kind", "포장종류", "header"), ("incoterms", "인도조건", "header"), ("currency", "통화", "header"),
               ("total_amount", "결제금액", "header"), ("payment", "결제방법", "header"), ("co_present", "원산지증명서 유무", "header"),
               ("description", "품명", "line"), ("hs_code", "세번부호", "line"), ("qty", "수량", "line"), ("unit", "단위", "line"),
               ("net_kg", "순중량(kg)", "line"), ("unit_price", "단가", "line"), ("amount", "금액", "line"),
               ("origin", "원산지", "line"), ("fta", "협정", "line"), ("origin_criterion", "원산지결정기준", "line")]
COUNTRY = {"CHINA": "CN", "VIETNAM": "VN"}


def blanks(errors, n_lines):
    """심은 오류 때문에 신고서에서 비워야 하는 칸 {(칸, 줄)}. 줄이 없는 칸은 줄 None.
    문제가 남은 칸은 비운다(e2e-plan C5). 송장 번호·컨테이너 오류는 신고서 칸이 아니라서 비울 칸이 없다."""
    out = set()
    every = range(1, n_lines + 1)
    for e in errors:
        f, doc, ln = e["field"].split(".")[-1], e["doc"], e["line"]
        if f == "total_qty":
            out.add(("qty", ln))
            if doc == "CI":                       # 상업송장 수량이 틀리면 그 줄 금액과 결제금액도 따라 틀린다
                out |= {("amount", ln), ("total_amount", None)}
        elif f in ("total_gross_kg", "total_amount", "total_packages"):
            out.add((f, None))
        elif f == "freight_term":
            out.add(("incoterms", None))
        elif f == "hs_code":
            out.add(("hs_code", ln))
        elif f == "origin_criterion":
            out |= {("origin_criterion", ln), ("fta", ln)}
        elif f in ("issue_date", "departure_date"):   # 원산지증명서를 그대로 믿을 수 없음 → 협정 적용 칸을 비운다
            out |= {(k, n) for k in ("fta", "origin_criterion") for n in every}
    return out


def declarations(sets, P, I):
    rows = []
    for s in sets:
        lines = kit.set_lines(s, I)
        t = gen.totals(lines)
        ex, con = P[s["exporter_id"]], P[s["consignee_id"]]
        empty = blanks(kit.errors_of(s), len(lines))
        crit = s["co_criteria"].split("|") if s["co_form"] else [""] * len(lines)
        head = {"bl_no": (s["bl_no"], "bill_of_lading.bl_no"), "vessel": (s["vessel_voyage"], "bill_of_lading.vessel_voyage"),
                "importer": (con["name"], "commercial_invoice.consignee_name"),
                "supplier": (ex["name"], "commercial_invoice.exporter_name"),
                "export_country": (COUNTRY[ex["country"]], "bill_of_lading.port_loading"),
                "total_gross_kg": (gen.fmt_num(t["gross"]), "packing_list.total_gross_kg"),
                "total_packages": (str(t["ctns"]), "packing_list.total_packages"), "package_kind": ("CT", "packing_list"),
                "incoterms": (s["incoterms"].split()[0], "commercial_invoice.incoterms"), "currency": ("USD", "commercial_invoice"),
                "total_amount": (gen.fmt_num(t["amount"]), "commercial_invoice.total_amount"),
                "payment": (s["payment_term"], "commercial_invoice.payment_term"),
                "co_present": ("Y" if s["co_form"] else "N", "certificate_of_origin")}
        for key, label, level in DECL_FIELDS:
            if level == "header":
                v, src = head[key]
                rows.append([s["set_id"], s["split"], "", key, label, v, src, int((key, None) in empty)])
        for n, (it, q) in enumerate(lines, 1):
            _, net, _, _ = gen.line_calc(it, q)
            i0 = n - 1
            vals = {"description": (it["description"], f"commercial_invoice.items[{i0}].name"),
                    "hs_code": (it["hs10_answer"], "eval/sets.csv hs_answer (관세청 HS부호 표)"),
                    "qty": (str(q), f"commercial_invoice.items[{i0}].qty"), "unit": (it["unit"], f"commercial_invoice.items[{i0}].qty"),
                    "net_kg": (gen.fmt_num(net), f"packing_list.items[{i0}].net_kg"),
                    "unit_price": (gen.fmt_num(it["unit_price_usd"]), f"commercial_invoice.items[{i0}].unit_price"),
                    "amount": (gen.fmt_num(gen.rnd(q * it["unit_price_usd"])), f"commercial_invoice.items[{i0}].amount"),
                    "origin": (COUNTRY[ex["country"]], "commercial_invoice.origin"),
                    "fta": (s["co_form"], "certificate_of_origin"),
                    "origin_criterion": (crit[i0], f"certificate_of_origin.items[{i0}].origin_criterion")}
            for key, label, level in DECL_FIELDS:
                if level == "line":
                    v, src = vals[key]
                    rows.append([s["set_id"], s["split"], n, key, label, v, src, int((key, n) in empty)])
    return rows


# ── 가상 화물 기록과 현황 질문 ───────────────────────────────────────────────
def week_of(d):
    start = d - dt.timedelta(days=d.weekday())
    return start, start + dt.timedelta(days=6)


def is_delayed(sh, today):
    return dt.date.fromisoformat(sh["arrived_at"]) <= today - dt.timedelta(days=DELAY_DAYS) and sh["customs_status"] not in CLEARED


def make_shipments(parties, items):
    """기준일 기준으로 지난 4주의 가상 화물 기록. 지연 건이 이번 주·지난주에 들어가게 비율을 맞춘다."""
    rng = random.Random("6:shipments")
    this_mon, _ = week_of(TODAY)
    last_mon = this_mon - dt.timedelta(days=7)
    spans = {"earlier": (this_mon - dt.timedelta(days=27), last_mon - dt.timedelta(days=1)),
             "last_week": (last_mon, this_mon - dt.timedelta(days=1)), "this_week": (this_mon, TODAY)}
    by_buyer = {}
    for it in items:
        by_buyer.setdefault(it["buyer_group"], []).append(it)
    out, seq = [], rng.randint(3000, 3500)
    for bucket, n in SEED_COUNT.items():
        lo, hi = spans[bucket]
        for k in range(n):
            arrived = lo + dt.timedelta(days=rng.randint(0, (hi - lo).days))
            if bucket == "this_week" and k < 3:
                arrived = TODAY                                   # 오늘 입항 몇 건
            age = (TODAY - arrived).days
            delayed = age >= DELAY_DAYS and rng.random() < (0.35 if bucket != "earlier" else 0.08)
            if age == 0:
                status = rng.choice(["입항", "입항", "수입신고"])
            elif delayed:
                status = rng.choice(["수입신고", "심사 중", "검사 중"])
            elif age < DELAY_DAYS:
                status = rng.choice(["수입신고", "심사 중", "검사 중", "수리"])
            else:
                status = rng.choice(["수리", "반출", "반출"])
            done = arrived + dt.timedelta(days=rng.randint(1, min(4, max(1, age))))
            last = min(TODAY, done) if status in CLEARED else arrived + dt.timedelta(days=rng.randint(0, age))
            buyer = rng.choice(["general", "general", "home", "food"])
            it = rng.choice(by_buyer[buyer])
            con = {"food": "KR04", "home": rng.choice(["KR05", "KR01"])}.get(buyer, rng.choice(["KR01", "KR02", "KR03"]))
            carrier = rng.choice(gen.CARRIERS)
            port = rng.choice(["SHA", "SZX", "NGB", "TAO", "CAN", "SGN", "HPH"])
            seq += rng.randint(1, 9)
            out.append({"bl_no": f"{carrier[1]}{port}{arrived.year % 100:02d}{seq:06d}", "consignee": CONSIGNEE_KO[con],
                        "item": ITEM_KO[it["bl_desc"]], "arrived_at": arrived.isoformat(), "customs_status": status,
                        "last_event_at": last.isoformat(), "job_id": None})
    return sorted(out, key=lambda r: (r["arrived_at"], r["bl_no"]))


def resolve(period, date_from=None, date_to=None):
    if period == "today":
        return TODAY, TODAY
    if period == "this_week":
        return week_of(TODAY)
    if period == "last_week":
        a, b = week_of(TODAY - dt.timedelta(days=7))
        return a, b
    if period == "range":
        return dt.date.fromisoformat(date_from), dt.date.fromisoformat(date_to)
    return None


UNTIL_TODAY = "today"  # 끝일이 '오늘'인 질문. 정답지에는 기준일을 적고 date_to_today를 붙인다 (다른 날 다시 계산, #170)
QUESTIONS = [  # (질문, 상태, 기간, 시작, 끝)
    ("이번 주 통관 지연 건 알려줘", "통관 지연", "this_week", None, None),
    ("지난주에 통관 지연된 화물 있어?", "통관 지연", "last_week", None, None),
    ("지금 통관이 늦어지고 있는 화물 전부 보여줘", "통관 지연", None, None, None),
    ("오늘 입항한 화물 몇 건이야?", None, "today", None, None),
    ("이번 주에 들어온 화물은 몇 건이야?", None, "this_week", None, None),
    ("지난주 입항 화물 목록 보여줘", None, "last_week", None, None),
    ("이번 주 입항한 것 중 검사 중인 건?", "검사 중", "this_week", None, None),
    ("심사 중인 화물 전체 알려줘", "심사 중", None, None, None),
    ("지난주에 들어와서 아직 수입신고 단계인 건?", "수입신고", "last_week", None, None),
    ("이번 주에 입항해서 수리된 화물은?", "수리", "this_week", None, None),
    ("지난주 입항 화물 중 반출까지 끝난 건 몇 건이야?", "반출", "last_week", None, None),
    ("11월 2일부터 11월 8일까지 입항한 화물", None, "range", "2026-11-02", "2026-11-08"),
    ("11월 9일에서 13일 사이에 들어온 화물 중 통관 지연 건", "통관 지연", "range", "2026-11-09", "2026-11-13"),
    ("10월에 입항한 화물 몇 건이야?", None, "range", "2026-10-01", "2026-10-31"),
    ("오늘 들어온 화물 중 통관 지연 건은?", "통관 지연", "today", None, None),
    ("오늘 입항해서 아직 입항 상태인 화물", "입항", "today", None, None),
    ("11월 1일부터 오늘까지 입항해서 반출된 화물", "반출", "range", "2026-11-01", UNTIL_TODAY),
    ("지금 검사 중인 화물 몇 건이야?", "검사 중", None, None, None),
    ("이번 주 입항해서 수입신고 들어간 건", "수입신고", "this_week", None, None),
    ("다음 주(11월 23일~29일) 입항 화물 있어?", None, "range", "2026-11-23", "2026-11-29"),
]
# 조회하지 않아야 하는 질문 (#165 FB08). 조회 칸(상태 하나·기간)으로 못 담는 조건은 '안내', 조건이 없으면 '되묻기'.
# 정답 건수는 0(rows를 돌려주지 않음). unsupported는 모델이 적을 말의 예이고 채점은 비었는지만 본다
NOT_QUERIED = [  # (질문, unsupported 예, 답 종류)
    ("이그잼플유통 화물만 보여줘", ["수하인 이그잼플유통"], "안내"),
    ("EXSHSZX26003555 지금 어디까지 진행됐어?", ["B/L 번호 EXSHSZX26003555"], "안내"),
    ("오늘 점심 뭐 먹지?", [], "되묻기"),
    ("통관 끝난 화물 몇 건이야?", ["상태 둘 이상: 수리, 반출"], "안내"),
]


def queries(shipments):
    """질문마다 기대 조건과 기대 건수. 기간은 입항일(arrived_at) 기준, '통관 지연'은 DELAY_DAYS 규칙으로 코드가 센다."""
    rows = []
    for i, (q, status, period, a, b) in enumerate(QUESTIONS, 1):
        until_today = b == UNTIL_TODAY
        b = TODAY.isoformat() if until_today else b
        rng = resolve(period, a, b)
        hits = [sh for sh in shipments
                if (rng is None or rng[0] <= dt.date.fromisoformat(sh["arrived_at"]) <= rng[1])
                and (status is None or (is_delayed(sh, TODAY) if status == "통관 지연" else sh["customs_status"] == status))]
        cond = {"status": status, "period": period, "date_from": a, "date_to": b, "today": TODAY.isoformat(),
                "period_resolved": {"from": rng[0].isoformat(), "to": rng[1].isoformat()} if rng else None,
                "rule": f"입항 후 {DELAY_DAYS}일 지나도 수리·반출 아님" if status == "통관 지연" else None}
        if until_today:
            cond["date_to_today"] = True  # samples/seed_dates.py가 다른 날에는 끝일을 그날로 바꾼다
        rows.append([f"Q{i:02d}", q, json.dumps(cond, ensure_ascii=False), len(hits)])
    for i, (q, unsupported, expect) in enumerate(NOT_QUERIED, len(QUESTIONS) + 1):
        cond = {"status": None, "period": None, "date_from": None, "date_to": None, "today": TODAY.isoformat(),
                "period_resolved": None, "rule": None, "unsupported": unsupported, "expect": expect}
        rows.append([f"Q{i:02d}", q, json.dumps(cond, ensure_ascii=False), 0])
    return rows


def write_csv(path, head, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)


def main():
    parties = kit.read_csv("parties.csv")
    items = kit.read_csv("items.csv")
    sets = kit.read_csv("sets.csv")
    I = kit.catalog_items(items + kit.read_csv("items_test.csv"))
    P = {p["party_id"]: p for p in parties + kit.read_csv("parties_test.csv")}
    head = ["set_id", "split", "line", "field", "label", "answer", "source", "expect_blank"]
    dev = declarations(sets, P, I)
    write_csv(kit.EVAL / "declarations.csv", head, dev)
    msg = f"신고서 정답: 개발용 {len(sets)}세트 {len(dev)}칸 (비워야 할 칸 {sum(r[-1] for r in dev)})"
    if kit.TEST_SETS.exists():
        test_sets = kit.read_csv("sets_test.csv")
        test = declarations(test_sets, P, I)
        write_csv(kit.EVAL_TEST / "declarations.csv", head, test)
        msg += f" · 발표용 {len(test_sets)}세트 {len(test)}칸"
    print(msg)
    shipments = make_shipments(parties, gen.load_catalog("items.csv"))   # 개발용 카탈로그만 (발표용 전용 품목은 쓰지 않는다)
    SHIPMENTS.write_text(json.dumps(shipments, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    q = queries(shipments)
    write_csv(QUERIES, ["query_id", "question", "expected_conditions", "expected_count"], q)
    week = week_of(TODAY)
    this_week = [s for s in shipments if week[0].isoformat() <= s["arrived_at"] <= week[1].isoformat()]
    print(f"화물 기록: {len(shipments)}건 (기준일 {TODAY}, 이번 주 {len(this_week)}건, 통관 지연 "
          f"{sum(is_delayed(s, TODAY) for s in shipments)}건) → {SHIPMENTS.relative_to(ROOT)}")
    print(f"현황 질문: {len(q)}개, 기대 건수 {[r[3] for r in q]} → {QUERIES.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
