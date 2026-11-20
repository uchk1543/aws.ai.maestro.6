"""합성 수입 서류 세트 생성기.

화물 1건의 정답(shipment)을 먼저 만들고, 같은 정답으로 B/L, Commercial Invoice,
Packing List, Certificate of Origin 4종을 PDF로 그린다. 오류 세트는 서류 1개의 인쇄값만
바꾸고 바꾼 내용을 injected_errors에 남긴다.

실행:  python data/generator/generate_documents.py [--base-date 2026-11-19] [--seed 20261120]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from catalog import BUYERS, CARRIERS, ITEMS, ORDER_BANK, PORTS, SUPPLIERS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
PAGE_W, PAGE_H = A4
MARGIN = 36

# ---------------------------------------------------------------------------
# 세트 계획: 정상 10 + 오류 5. 오류 7종이 모두 한 번 이상 나온다.
# ---------------------------------------------------------------------------
SET_PLANS = [
    dict(supplier="S1", items=["battery", "led"], incoterms="CIF"),
    dict(supplier="S2", items=["notebook", "smartphone"], incoterms="CIF"),
    dict(supplier="S3", items=["tshirt"], incoterms="FOB"),
    dict(supplier="S4", items=["shrimp"], incoterms="CIF"),
    dict(supplier="S5", items=["bolt", "nut", "machine_parts"], incoterms="CIF"),
    dict(supplier="S6", items=["storage_box", "sink"], incoterms="FOB"),
    dict(supplier="S7", items=["wardrobe"], incoterms="CIF", to_order=True),
    dict(supplier="S8", items=["coffee"], incoterms="CIF"),
    dict(supplier="S2", items=["smartphone", "elec_components"], incoterms="CIF"),
    dict(supplier="S9", items=["tyre"], incoterms="FOB"),
    # SET-011: 데모용 "입항 3일 전" 세트. 중량 불일치 + 컨테이너 체크디지트 오류 2건
    dict(supplier="S1", items=["battery"], incoterms="CIF", demo=True,
         errors=["gross_weight_digit_swap", "container_check_digit"]),
    dict(supplier="S5", items=["bolt", "nut"], incoterms="CIF", errors=["package_count_mismatch"]),
    dict(supplier="S2", items=["notebook"], incoterms="CIF", errors=["invoice_total_mismatch"]),
    dict(supplier="S3", items=["tshirt"], incoterms="CIF", errors=["invoice_ref_typo", "origin_mismatch"]),
    dict(supplier="S6", items=["storage_box"], incoterms="FOB", errors=["missing_customs_value_info"]),
]

# 오류 종류 → 검증 규칙, 관련 서류, 기대 판정
ERROR_RULES = {
    "gross_weight_digit_swap": ("gross_weight_match", ["bill_of_lading", "packing_list"], "error"),
    "package_count_mismatch": ("package_count_match", ["bill_of_lading", "packing_list"], "error"),
    "container_check_digit": ("container_check_digit", ["bill_of_lading"], "error"),
    "invoice_total_mismatch": ("invoice_amount_sum", ["commercial_invoice"], "error"),
    "invoice_ref_typo": ("invoice_reference_match", ["packing_list", "commercial_invoice"], "error"),
    "origin_mismatch": ("origin_match", ["commercial_invoice", "certificate_of_origin"], "error"),
    "missing_customs_value_info": ("customs_value_info", ["commercial_invoice"], "missing_warning"),
}

# ---------------------------------------------------------------------------
# 공통 도구
# ---------------------------------------------------------------------------
_ISO_LETTERS: dict[str, int] = {}
_v = 10
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    if _v % 11 == 0:
        _v += 1
    _ISO_LETTERS[_ch] = _v
    _v += 1


def iso6346_check_digit(first10: str) -> int:
    """컨테이너 번호 앞 10자리(소유자 3 + 구분 1 + 일련번호 6)의 체크디지트."""
    total = 0
    for i, ch in enumerate(first10):
        val = _ISO_LETTERS[ch] if ch.isalpha() else int(ch)
        total += val * (2 ** i)
    return total % 11 % 10


def make_container_no(owner_code: str, rng: random.Random) -> str:
    serial = f"{rng.randint(0, 999999):06d}"
    first10 = owner_code + serial
    return first10 + str(iso6346_check_digit(first10))


def fmt_num(v: float, decimals: int = 2) -> str:
    return f"{v:,.{decimals}f}"


def fmt_date(d: date, style: str) -> str:
    if style == "iso":
        return d.isoformat()
    if style == "dmy_upper":
        return d.strftime("%d %b %Y").upper()
    if style == "mdy":
        return d.strftime("%b. %d, %Y")
    if style == "dmy_slash":
        return d.strftime("%d/%m/%Y")
    raise ValueError(style)


_ONES = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN",
         "ELEVEN", "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN",
         "EIGHTEEN", "NINETEEN"]
_TENS = ["", "", "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY"]


def num_to_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + " HUNDRED" + ("" if rest == 0 else " " + num_to_words(rest))
    rest = n % 1000
    return num_to_words(n // 1000) + " THOUSAND" + ("" if rest == 0 else " " + num_to_words(rest))


def unit_price_decimals(price: float) -> int:
    return 3 if price < 1 else 2


PKG_ABBR = {"CARTONS": "CTNS", "BAGS": "BAGS", "PCS": "PCS", "PACKAGES": "PKGS"}


def wrap(text: str, width: float, size: float, font: str = "Helvetica") -> list[str]:
    """폭에 맞춰 줄바꿈한다. 원래 줄바꿈(\\n)은 유지한다."""
    out = []
    for para in str(text).split("\n"):
        words, line = para.split(" "), ""
        for w in words:
            cand = w if not line else line + " " + w
            if stringWidth(cand, font, size) <= width:
                line = cand
            else:
                if line:
                    out.append(line)
                line = w
        out.append(line)
    return out


# ---------------------------------------------------------------------------
# 1) 정답 화물 만들기
# ---------------------------------------------------------------------------
def build_shipment(set_no: int, plan: dict, rng: random.Random, base_date: date) -> dict:
    sup = SUPPLIERS[plan["supplier"]]
    buyer = BUYERS[sup["buyer"]]
    carrier = rng.choice(CARRIERS)

    on_board = base_date - timedelta(days=rng.randint(8, 22))
    if plan.get("demo"):
        # 데모 세트: 어제 선적, 오늘 서류 도착, 3일 뒤 부산 입항 (D-3)
        on_board = base_date - timedelta(days=1)
    invoice_date = on_board - timedelta(days=rng.randint(1, 5))
    co_issue = on_board - timedelta(days=rng.randint(0, 2))

    lines = []
    for idx, key in enumerate(plan["items"], start=1):
        it = ITEMS[key]
        pkgs = rng.randint(*it["pkgs"])
        qty = pkgs * it["units_per_pkg"]
        lo, hi = it["price"]
        dec = unit_price_decimals(lo)
        unit_price = round(rng.uniform(lo, hi), dec)
        amount = round(qty * unit_price, 2)
        nw = round(qty * it["nw_per_unit"], 2)
        gw = round(nw + pkgs * it["tare_per_pkg"], 2)
        cbm = round(pkgs * it["cbm_per_pkg"], 3)
        lines.append({
            "line_no": idx, "item_key": key, "item_code": it["code"],
            "description": it["description"], "quantity": qty, "unit": it["unit"],
            "unit_price": unit_price, "amount": amount,
            "packages": pkgs, "package_type": it["pkg_type"],
            "net_weight_kg": nw, "gross_weight_kg": gw, "cbm": cbm,
            "hs6_expected": it["hs6"], "hs6_declared_on_co": it["hs6"] or it.get("co_hs6"),
        })

    total_pkgs = sum(l["packages"] for l in lines)
    pkg_types = {l["package_type"] for l in lines}
    totals = {
        "quantity": sum(l["quantity"] for l in lines),
        "amount": round(sum(l["amount"] for l in lines), 2),
        "packages": total_pkgs,
        "package_type": pkg_types.pop() if len(pkg_types) == 1 else "PACKAGES",
        "net_weight_kg": round(sum(l["net_weight_kg"] for l in lines), 2),
        "gross_weight_kg": round(sum(l["gross_weight_kg"] for l in lines), 2),
        "cbm": round(sum(l["cbm"] for l in lines), 3),
    }

    reefer = any(ITEMS[k].get("reefer") for k in plan["items"])
    cbm = totals["cbm"]
    if reefer:
        n_cont, ctype = (1 if cbm <= 58 else 2), "40RH"
    elif cbm <= 28:
        n_cont, ctype = 1, "20GP"
    elif cbm <= 66:
        n_cont, ctype = 1, "40HC"
    else:
        n_cont, ctype = 2, "40HC"
    containers = [{
        "container_no": make_container_no(carrier["owner_code"], rng),
        "seal_no": f"{carrier['key']}{rng.randint(1000000, 9999999)}",
        "type": ctype,
    } for _ in range(n_cont)]

    incoterms = plan["incoterms"]
    pol = sup["pol"]
    freight = insurance = None
    withheld = None
    if incoterms == "FOB":
        freight = round(n_cont * rng.uniform(900, 1900), 2)
        insurance = round((totals["amount"] + freight) * 1.1 * rng.uniform(0.0008, 0.0015), 2)
        if "missing_customs_value_info" in plan.get("errors", []):
            # 서류에는 빠져 있고, 정정본에서만 채워지는 값
            withheld = {"freight_amount": freight, "insurance_amount": insurance}
            freight = insurance = None

    consignee = ({"name": f"TO ORDER OF {ORDER_BANK}", "address": []}
                 if plan.get("to_order") else {"name": buyer["name"], "address": buyer["address"]})

    invoice_no = f"{sup['inv_prefix']}-{invoice_date:%y%m}-{rng.randint(100, 999)}"
    return {
        "set_id": f"SET-{set_no:03d}",
        "shipper": {"name": sup["name"], "address": sup["address"]},
        "seller": {"name": sup["name"], "address": sup["address"]},
        "consignee": consignee,
        "notify_party": {"name": buyer["name"], "address": buyer["address"]},
        "buyer": {"name": buyer["name"], "address": buyer["address"], "short": buyer["short"]},
        "carrier": carrier["name"],
        "bl_no": f"{carrier['key']}{on_board:%y%m}{rng.randint(100000, 999999)}",
        "vessel": rng.choice(carrier["vessels"]),
        "voyage": f"{rng.randint(1, 99):03d}{rng.choice('EWNS')}",
        "port_of_loading": {"locode": pol, "name": PORTS[pol]},
        "port_of_discharge": {"locode": "KRPUS", "name": PORTS["KRPUS"]},
        "on_board_date": on_board.isoformat(),
        "freight_terms": "FREIGHT PREPAID" if incoterms in ("CIF", "CFR") else "FREIGHT COLLECT",
        "containers": containers,
        "reefer_temp": "-18 C" if reefer else None,
        "invoice_no": invoice_no,
        "invoice_date": invoice_date.isoformat(),
        "po_no": f"PO-{buyer['short']}-{invoice_date:%y}-{rng.randint(1000, 9999)}",
        "incoterms": incoterms,
        "incoterms_place": "BUSAN" if incoterms in ("CIF", "CFR") else PORTS[pol].split(",")[0],
        "currency": "USD",
        "payment_terms": rng.choice(["T/T 30 DAYS AFTER B/L DATE", "T/T IN ADVANCE", "L/C AT SIGHT"]),
        "freight_amount": freight,
        "insurance_amount": insurance,
        "withheld_customs_value": withheld,
        "country_of_origin": sup["country_name"],
        "co_certificate_no": f"CO{co_issue:%y}{sup['country']}{rng.randint(100000, 999999)}",
        "co_issue_date": co_issue.isoformat(),
        "items": lines,
        "totals": totals,
        "shipping_marks": [buyer["short"], "BUSAN, KOREA", f"C/NO. 1-{total_pkgs}",
                           f"MADE IN {sup['country_name']}"],
    }


# ---------------------------------------------------------------------------
# 2) 서류별 인쇄값 (정상이면 정답과 같다)
# ---------------------------------------------------------------------------
def printed_fields(s: dict) -> dict:
    return {
        "bill_of_lading": {
            "bl_no": s["bl_no"], "carrier": s["carrier"],
            "shipper_name": s["shipper"]["name"], "consignee_name": s["consignee"]["name"],
            "notify_party_name": s["notify_party"]["name"],
            "vessel": s["vessel"], "voyage": s["voyage"],
            "port_of_loading": s["port_of_loading"]["name"],
            "port_of_discharge": s["port_of_discharge"]["name"],
            "container_numbers": [c["container_no"] for c in s["containers"]],
            "seal_numbers": [c["seal_no"] for c in s["containers"]],
            "total_packages": s["totals"]["packages"], "package_type": s["totals"]["package_type"],
            "gross_weight_kg": s["totals"]["gross_weight_kg"], "measurement_cbm": s["totals"]["cbm"],
            "cargo_description": [l["description"] for l in s["items"]],
            "freight_terms": s["freight_terms"], "on_board_date": s["on_board_date"],
        },
        "commercial_invoice": {
            "invoice_no": s["invoice_no"], "invoice_date": s["invoice_date"], "po_no": s["po_no"],
            "seller_name": s["seller"]["name"], "buyer_name": s["buyer"]["name"],
            "incoterms": s["incoterms"], "incoterms_place": s["incoterms_place"],
            "currency": s["currency"], "payment_terms": s["payment_terms"],
            "line_items": [{"description": l["description"], "quantity": l["quantity"], "unit": l["unit"],
                            "unit_price": l["unit_price"], "amount": l["amount"]} for l in s["items"]],
            "total_amount": s["totals"]["amount"],
            "freight_amount": s["freight_amount"], "insurance_amount": s["insurance_amount"],
            "country_of_origin": s["country_of_origin"],
        },
        "packing_list": {
            "invoice_no_ref": s["invoice_no"], "date": s["invoice_date"],
            "shipper_name": s["shipper"]["name"], "consignee_name": s["buyer"]["name"],
            "line_items": [{"description": l["description"], "quantity": l["quantity"],
                            "packages": l["packages"], "net_weight_kg": l["net_weight_kg"],
                            "gross_weight_kg": l["gross_weight_kg"], "cbm": l["cbm"]} for l in s["items"]],
            "total_packages": s["totals"]["packages"],
            "total_net_weight_kg": s["totals"]["net_weight_kg"],
            "total_gross_weight_kg": s["totals"]["gross_weight_kg"],
            "total_cbm": s["totals"]["cbm"],
            "shipping_marks": s["shipping_marks"],
        },
        "certificate_of_origin": {
            "certificate_no": s["co_certificate_no"], "issue_date": s["co_issue_date"],
            "exporter_name": s["shipper"]["name"], "consignee_name": s["buyer"]["name"],
            "country_of_origin": s["country_of_origin"],
            "invoice_no_ref": s["invoice_no"], "invoice_date_ref": s["invoice_date"],
            "items": [{"description": l["description"], "hs_code": l["hs6_declared_on_co"],
                       "quantity": l["quantity"], "unit": l["unit"]} for l in s["items"]],
            "transport": f"{s['vessel']} {s['voyage']} / {s['port_of_loading']['name']} TO BUSAN, KOREA",
        },
    }


def corrected_fields(s: dict) -> dict:
    """정정이 끝난 서류의 인쇄값. 누락됐던 운임·보험료도 채운다."""
    p = printed_fields(s)
    if s.get("withheld_customs_value"):
        p["commercial_invoice"].update(s["withheld_customs_value"])
    return p


# ---------------------------------------------------------------------------
# 3) 오류 넣기
# ---------------------------------------------------------------------------
def swap_digits(value: float) -> float:
    int_part, frac = f"{value:.2f}".split(".")
    digits = list(int_part)
    for i in range(len(digits) - 1):
        if digits[i] != digits[i + 1]:
            digits[i], digits[i + 1] = digits[i + 1], digits[i]
            return float("".join(digits) + "." + frac)
    return value + 100.0


def apply_errors(s: dict, printed: dict, errors: list[str]) -> list[dict]:
    log = []
    for err in errors:
        rule, docs, expected = ERROR_RULES[err]
        entry = {"error_type": err, "rule": rule, "documents": docs, "expected_result": expected}
        if err == "gross_weight_digit_swap":
            pl = printed["packing_list"]
            old = pl["total_gross_weight_kg"]
            pl["total_gross_weight_kg"] = swap_digits(old)
            entry |= {"document": "packing_list", "field": "total_gross_weight_kg",
                      "correct_value": old, "printed_value": pl["total_gross_weight_kg"]}
        elif err == "package_count_mismatch":
            bl = printed["bill_of_lading"]
            old = bl["total_packages"]
            bl["total_packages"] = old - 1
            entry |= {"document": "bill_of_lading", "field": "total_packages",
                      "correct_value": old, "printed_value": old - 1}
        elif err == "container_check_digit":
            bl = printed["bill_of_lading"]
            old = bl["container_numbers"][0]
            bad = old[:-1] + str((int(old[-1]) + 1) % 10)
            bl["container_numbers"][0] = bad
            entry |= {"document": "bill_of_lading", "field": "container_numbers[0]",
                      "correct_value": old, "printed_value": bad}
        elif err == "invoice_total_mismatch":
            ci = printed["commercial_invoice"]
            old = ci["total_amount"]
            ci["total_amount"] = round(old + 1000.0, 2)
            entry |= {"document": "commercial_invoice", "field": "total_amount",
                      "correct_value": old, "printed_value": ci["total_amount"]}
        elif err == "invoice_ref_typo":
            pl = printed["packing_list"]
            old = pl["invoice_no_ref"]
            bad = old[:-1] + str((int(old[-1]) + 1) % 10)
            pl["invoice_no_ref"] = bad
            entry |= {"document": "packing_list", "field": "invoice_no_ref",
                      "correct_value": old, "printed_value": bad}
        elif err == "origin_mismatch":
            co = printed["certificate_of_origin"]
            old = co["country_of_origin"]
            co["country_of_origin"] = "CHINA" if old != "CHINA" else "VIETNAM"
            entry |= {"document": "certificate_of_origin", "field": "country_of_origin",
                      "correct_value": old, "printed_value": co["country_of_origin"]}
        elif err == "missing_customs_value_info":
            entry |= {"document": "commercial_invoice", "field": "freight_amount, insurance_amount",
                      "correct_value": None, "printed_value": None,
                      "note": "FOB 조건인데 운임·보험료 정보가 어느 서류에도 없다. 과세가격(CIF) 산정 불가"}
        log.append(entry)
    return log


def expected_findings(s: dict, injected: list[dict]) -> list[dict]:
    out = [{"rule": e["rule"], "severity": e["expected_result"], "documents": e["documents"]}
           for e in injected]
    if any(e["error_type"] == "gross_weight_digit_swap" for e in injected):
        out.append({"rule": "pl_gross_weight_sum", "severity": "error", "documents": ["packing_list"],
                    "note": "PL 품목별 총중량 합계와 PL 합계 칸이 다름. 잡아내면 추가 점수"})
    if s["consignee"]["name"].startswith("TO ORDER"):
        out.append({"rule": "party_consistency", "severity": "info",
                    "documents": ["bill_of_lading", "commercial_invoice"],
                    "note": "지시식 B/L이라 Consignee가 Buyer와 다름. 오류가 아니라 참고"})
    for l in s["items"]:
        if l["hs6_expected"] is None:
            out.append({"rule": "hs_clarification_needed", "severity": "info",
                        "documents": ["commercial_invoice"],
                        "note": f"'{l['description']}' 품명만으로 HS 분류 불가. 재질·용도를 되물어야 함"})
    return out


# ---------------------------------------------------------------------------
# 4) PDF 그리기
# ---------------------------------------------------------------------------
class Doc:
    def __init__(self, path: Path, title: str):
        self.c = canvas.Canvas(str(path), pagesize=A4)
        self.c.setTitle(title)
        self.c.setAuthor("Synthetic data generator (hackathon test data)")
        self.c.setSubject("SAMPLE - synthetic test data, not a valid trade document")
        self._watermark()

    def _watermark(self):
        c = self.c
        c.saveState()
        c.setFillColor(Color(0.6, 0.6, 0.6, alpha=0.18))
        c.setFont("Helvetica-Bold", 96)
        c.translate(PAGE_W / 2, PAGE_H / 2)
        c.rotate(35)
        c.drawCentredString(0, 0, "SAMPLE")
        c.restoreState()
        c.setFont("Helvetica-Oblique", 6.5)
        c.setFillColor(Color(0.35, 0.35, 0.35))
        c.drawCentredString(PAGE_W / 2, 18,
                            "SYNTHETIC SAMPLE FOR HACKATHON TESTING - FICTIONAL COMPANIES - NOT A VALID TRADE DOCUMENT")
        c.setFillColor(black)

    def text(self, x, y, s, size=9, bold=False, font=None):
        self.c.setFont(font or ("Helvetica-Bold" if bold else "Helvetica"), size)
        self.c.drawString(x, y, s)

    def rtext(self, x, y, s, size=9, bold=False):
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        self.c.drawRightString(x, y, s)

    def ctext(self, x, y, s, size=9, bold=False):
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        self.c.drawCentredString(x, y, s)

    def box(self, x, top, w, h, label, lines=(), size=8.5, label_size=6.5):
        self.c.setLineWidth(0.6)
        self.c.rect(x, top - h, w, h)
        self.text(x + 4, top - 9, label, size=label_size)
        y = top - 21
        for raw in lines:
            for ln in wrap(raw, w - 12, size):
                self.text(x + 6, y, ln, size=size)
                y -= size + 2.5

    def table(self, x, top, widths, headers, rows, row_h=15, size=8, aligns=None, header_size=7):
        c = self.c
        aligns = aligns or ["l"] * len(widths)
        total_w = sum(widths)
        c.setLineWidth(0.6)
        c.setFillColor(Color(0.93, 0.93, 0.93))
        c.rect(x, top - row_h - 4, total_w, row_h + 4, fill=1, stroke=1)
        c.setFillColor(black)
        cx = x
        for w, h in zip(widths, headers):
            self.text(cx + 3, top - row_h + 2, h, size=header_size, bold=True)
            cx += w
        y = top - row_h - 4
        for row in rows:
            cells = [wrap(v, w - 8, size) for w, v in zip(widths, row)]
            n_lines = max(len(cl) for cl in cells)
            rh = max(row_h, n_lines * (size + 3) + 6)
            c.rect(x, y - rh, total_w, rh)
            cx = x
            for w, cl, a in zip(widths, cells, aligns):
                for k, part in enumerate(cl):
                    ty = y - 11 - k * (size + 3)
                    if a == "r":
                        self.rtext(cx + w - 4, ty, part, size=size)
                    else:
                        self.text(cx + 4, ty, part, size=size)
                cx += w
            y -= rh
        cx = x
        for w in widths[:-1]:
            cx += w
            c.line(cx, top, cx, y)
        return y

    def save(self):
        self.c.showPage()
        self.c.save()


def _addr_lines(party: dict) -> list[str]:
    return [party["name"], *party.get("address", [])]


def render_bl(path: Path, s: dict, p: dict, variant: str):
    d = Doc(path, f"Bill of Lading {p['bl_no']}")
    L, R = MARGIN, PAGE_W - MARGIN
    mid = (L + R) / 2
    top = PAGE_H - MARGIN
    containers = "\n".join(f"{cn} / {sn} ({c['type']})" for cn, sn, c in
                           zip(p["container_numbers"], p["seal_numbers"], s["containers"]))
    desc = "\n".join(p["cargo_description"])
    if s["reefer_temp"]:
        desc += f"\nREEFER CARGO, SET TEMP {s['reefer_temp']}"
    if variant == "A":
        d.text(L, top - 14, p["carrier"], size=14, bold=True)
        d.rtext(R, top - 14, "BILL OF LADING", size=16, bold=True)
        d.rtext(R, top - 28, "FOR PORT-TO-PORT SHIPMENT", size=7)
        y = top - 40
        d.box(L, y, mid - L, 62, "Shipper", _addr_lines(s["shipper"]))
        d.box(mid, y, R - mid, 62, "B/L No.", [p["bl_no"]], size=12)
        y -= 62
        d.box(L, y, mid - L, 62, "Consignee", _addr_lines(s["consignee"]))
        d.box(mid, y, R - mid, 62, "Carrier", [p["carrier"], "Number of original B/Ls: THREE (3)"])
        y -= 62
        d.box(L, y, mid - L, 62, "Notify Party", _addr_lines(s["notify_party"]))
        d.box(mid, y, R - mid, 62, "Freight", [p["freight_terms"]])
        y -= 62
        q = (R - L) / 4
        d.box(L, y, q, 34, "Vessel / Voyage", [f"{p['vessel']} / {p['voyage']}"], size=8)
        d.box(L + q, y, q, 34, "Port of Loading", [p["port_of_loading"]], size=8)
        d.box(L + 2 * q, y, q, 34, "Port of Discharge", [p["port_of_discharge"]], size=8)
        d.box(L + 3 * q, y, q, 34, "Place of Delivery", ["BUSAN CY"], size=8)
        y -= 46
        y = d.table(L, y, [150, 70, 160, 72, 71],
                    ["Container No. / Seal No.", "No. of Packages", "Description of Goods",
                     "Gross Weight (KG)", "Measurement (CBM)"],
                    [[containers, f"{p['total_packages']:,} {p['package_type']}", "SAID TO CONTAIN:\n" + desc,
                      fmt_num(p["gross_weight_kg"]), fmt_num(p["measurement_cbm"], 3)]],
                    aligns=["l", "r", "l", "r", "r"])
        y -= 24
        d.text(L, y, f"Shipped on board date: {fmt_date(date.fromisoformat(p['on_board_date']), 'iso')}")
        d.text(L, y - 14, f"Place and date of issue: {s['port_of_loading']['name'].split(',')[0]}, "
                          f"{fmt_date(date.fromisoformat(p['on_board_date']), 'iso')}")
    else:
        d.text(L, top - 14, "OCEAN BILL OF LADING", size=15, bold=True)
        d.text(L, top - 28, p["carrier"], size=9)
        d.rtext(R, top - 14, "BILL OF LADING NO.", size=7)
        d.rtext(R, top - 30, p["bl_no"], size=13, bold=True)
        y = top - 42
        d.box(L, y, mid - L, 60, "SHIPPER/EXPORTER", _addr_lines(s["shipper"]))
        d.box(mid, y, R - mid, 60, "EXPORT REFERENCES", [f"INVOICE NO. {s['invoice_no']}"])
        y -= 60
        d.box(L, y, mid - L, 60, "CONSIGNEE (COMPLETE NAME AND ADDRESS)", _addr_lines(s["consignee"]))
        d.box(mid, y, R - mid, 60, "FORWARDING AGENT", ["AS ARRANGED"])
        y -= 60
        d.box(L, y, mid - L, 60, "NOTIFY PARTY", _addr_lines(s["notify_party"]))
        d.box(mid, y, R - mid, 60, "FREIGHT AND CHARGES", [p["freight_terms"]])
        y -= 60
        q = (R - L) / 4
        d.box(L, y, q, 34, "OCEAN VESSEL", [p["vessel"]], size=8)
        d.box(L + q, y, q, 34, "VOY. NO.", [p["voyage"]], size=8)
        d.box(L + 2 * q, y, q, 34, "PORT OF LOADING", [p["port_of_loading"]], size=8)
        d.box(L + 3 * q, y, q, 34, "PORT OF DISCHARGE", [p["port_of_discharge"]], size=8)
        y -= 46
        y = d.table(L, y, [165, 62, 166, 65, 65],
                    ["MARKS & NOS / CONTAINER & SEAL", "QUANTITY", "KIND OF PACKAGES; DESCRIPTION",
                     "G.W. (KGS)", "MEAS. (M3)"],
                    [["\n".join(s["shipping_marks"]) + "\n" + containers,
                      f"{p['total_packages']} {PKG_ABBR.get(p['package_type'], 'PKGS')}", desc,
                      fmt_num(p["gross_weight_kg"]) + " KGS", fmt_num(p["measurement_cbm"], 3)]],
                    aligns=["l", "r", "l", "r", "r"])
        y -= 18
        d.text(L, y, f"SAY: {num_to_words(p['total_packages'])} ({p['total_packages']}) "
                     f"{p['package_type']} ONLY", size=8.5, bold=True)
        d.text(L, y - 18, f"LADEN ON BOARD: {fmt_date(date.fromisoformat(p['on_board_date']), 'dmy_upper')}")
        d.text(L, y - 32, "NO. OF ORIGINAL B(S)/L: 3/3")
    d.text(R - 180, 70, "As agent for the carrier", size=7)
    d.c.line(R - 180, 60, R, 60)
    d.save()


def render_invoice(path: Path, s: dict, p: dict, variant: str):
    d = Doc(path, f"Commercial Invoice {p['invoice_no']}")
    L, R = MARGIN, PAGE_W - MARGIN
    mid = (L + R) / 2
    top = PAGE_H - MARGIN
    items = p["line_items"]

    def price(v):
        return fmt_num(v, unit_price_decimals(v))

    if variant == "A":
        d.text(L, top - 14, p["seller_name"], size=12, bold=True)
        for i, ln in enumerate(s["seller"]["address"]):
            d.text(L, top - 28 - i * 11, ln, size=8)
        d.ctext(PAGE_W / 2, top - 70, "COMMERCIAL INVOICE", size=16, bold=True)
        y = top - 84
        d.box(L, y, mid - L, 74, "Buyer / Consignee", _addr_lines(s["buyer"]))
        d.box(mid, y, R - mid, 74, "Invoice No. / Date / P.O. No.",
              [f"Invoice No.: {p['invoice_no']}",
               f"Invoice Date: {fmt_date(date.fromisoformat(p['invoice_date']), 'iso')}",
               f"P.O. No.: {p['po_no']}"])
        y -= 74
        d.box(L, y, mid - L, 46, "Terms of Delivery / Payment",
              [f"{p['incoterms']} {p['incoterms_place']} (INCOTERMS 2020)", p["payment_terms"]])
        d.box(mid, y, R - mid, 46, "Shipment",
              [f"FROM {s['port_of_loading']['name']}", "TO BUSAN, KOREA BY VESSEL"])
        y -= 58
        rows = [[str(i + 1), it["description"], f"{it['quantity']:,}", it["unit"], price(it["unit_price"]),
                 fmt_num(it["amount"])] for i, it in enumerate(items)]
        rows.append(["", "TOTAL", f"{sum(it['quantity'] for it in items):,}", "", "",
                     f"{p['currency']} {fmt_num(p['total_amount'])}"])
        y = d.table(L, y, [26, 230, 62, 40, 70, 95],
                    ["No.", "Description of Goods", "Quantity", "Unit", f"Unit Price ({p['currency']})",
                     f"Amount ({p['currency']})"], rows, aligns=["l", "l", "r", "l", "r", "r"])
        y -= 20
        d.text(L, y, f"Country of Origin: {p['country_of_origin']}")
        if p["freight_amount"] is not None:
            d.text(L, y - 14, f"Remarks: Ocean freight {p['currency']} {fmt_num(p['freight_amount'])} and "
                              f"marine insurance {p['currency']} {fmt_num(p['insurance_amount'])} "
                              f"arranged and paid by buyer.", size=8)
    else:
        d.text(L, top - 18, "INVOICE", size=20, bold=True)
        d.rtext(R, top - 12, p["seller_name"], size=9, bold=True)
        for i, ln in enumerate(s["seller"]["address"]):
            d.rtext(R, top - 24 - i * 10, ln, size=7)
        y = top - 56
        d.box(L, y, mid - L, 70, "SOLD TO", _addr_lines(s["buyer"]))
        d.box(mid, y, R - mid, 70, "",
              [f"Inv. No.     {p['invoice_no']}",
               f"Inv. Date    {fmt_date(date.fromisoformat(p['invoice_date']), 'mdy')}",
               f"Order Ref.   {p['po_no']}",
               f"Price Term   {p['incoterms']} {p['incoterms_place']}"])
        y -= 70
        d.box(L, y, R - L, 34, "SHIP TO / VIA",
              [f"{s['buyer']['name']}  -  VIA {s['port_of_loading']['name']} TO BUSAN BY SEA  -  "
               f"PAYMENT: {p['payment_terms']}"], size=8)
        y -= 46
        rows = [[s["items"][i]["item_code"], it["description"], f"{it['quantity']:,} {it['unit']}",
                 price(it["unit_price"]), fmt_num(it["amount"])] for i, it in enumerate(items)]
        y = d.table(L, y, [78, 222, 80, 70, 73],
                    ["Item Code", "Description of Goods", "Q'ty", "U/Price", "Total"], rows,
                    aligns=["l", "l", "r", "r", "r"])
        y -= 18
        d.rtext(R, y, f"TOTAL AMOUNT: {p['currency']} {fmt_num(p['total_amount'])}", size=10, bold=True)
        d.text(L, y - 22, f"MADE IN {p['country_of_origin']}", size=9, bold=True)
        if p["freight_amount"] is not None:
            d.text(L, y - 38, f"Freight (paid by buyer): {p['currency']} {fmt_num(p['freight_amount'])}   "
                              f"Insurance (paid by buyer): {p['currency']} {fmt_num(p['insurance_amount'])}",
                   size=8)
    d.text(R - 180, 82, "Authorized Signature", size=7)
    d.c.line(R - 180, 72, R, 72)
    d.text(R - 180, 62, p["seller_name"][:40], size=6.5)
    d.save()


def render_packing_list(path: Path, s: dict, p: dict, variant: str):
    d = Doc(path, f"Packing List {p['invoice_no_ref']}")
    L, R = MARGIN, PAGE_W - MARGIN
    mid = (L + R) / 2
    top = PAGE_H - MARGIN
    items = p["line_items"]
    if variant == "A":
        d.text(L, top - 14, p["shipper_name"], size=12, bold=True)
        for i, ln in enumerate(s["shipper"]["address"]):
            d.text(L, top - 28 - i * 11, ln, size=8)
        d.ctext(PAGE_W / 2, top - 70, "PACKING LIST", size=16, bold=True)
        y = top - 84
        d.box(L, y, mid - L, 70, "Consignee", _addr_lines(s["buyer"]))
        d.box(mid, y, R - mid, 70, "Reference",
              [f"Ref. Invoice No.: {p['invoice_no_ref']}",
               f"Date: {fmt_date(date.fromisoformat(p['date']), 'iso')}",
               f"Vessel/Voyage: {s['vessel']} / {s['voyage']}"])
        y -= 82
        rows = [[it["description"], f"{it['quantity']:,}", f"{it['packages']:,}", fmt_num(it["net_weight_kg"]),
                 fmt_num(it["gross_weight_kg"]), fmt_num(it["cbm"], 3)] for it in items]
        rows.append(["TOTAL", "", f"{p['total_packages']:,} {s['totals']['package_type']}",
                     fmt_num(p["total_net_weight_kg"]), fmt_num(p["total_gross_weight_kg"]),
                     fmt_num(p["total_cbm"], 3)])
        y = d.table(L, y, [205, 58, 75, 60, 60, 65],
                    ["Description", "Quantity", "Packages", "N.W. (KG)", "G.W. (KG)", "Meas. (CBM)"],
                    rows, aligns=["l", "r", "r", "r", "r", "r"])
        y -= 22
        d.text(L, y, "Shipping Marks:", bold=True)
        for i, m in enumerate(p["shipping_marks"]):
            d.text(L + 10, y - 13 - i * 11, m, size=8.5)
    else:
        d.text(L, top - 18, "PACKING LIST", size=18, bold=True)
        d.rtext(R, top - 12, p["shipper_name"], size=9, bold=True)
        for i, ln in enumerate(s["shipper"]["address"]):
            d.rtext(R, top - 24 - i * 10, ln, size=7)
        y = top - 56
        d.box(L, y, mid - L, 64, "MESSRS.", _addr_lines(s["buyer"]))
        d.box(mid, y, R - mid, 64, "",
              [f"Invoice Ref : {p['invoice_no_ref']}",
               f"Date        : {fmt_date(date.fromisoformat(p['date']), 'dmy_upper')}",
               f"From/To     : {s['port_of_loading']['locode']} -> KRPUS"])
        y -= 76
        rows, start = [], 1
        for it in items:
            end = start + it["packages"] - 1
            rows.append([f"{start}-{end}", it["description"], f"{it['quantity']:,}",
                         fmt_num(it["net_weight_kg"]), fmt_num(it["gross_weight_kg"]), fmt_num(it["cbm"], 3)])
            start = end + 1
        y = d.table(L, y, [62, 218, 58, 60, 60, 65],
                    ["C/No.", "Description", "Q'ty", "N/W (KGS)", "G/W (KGS)", "CBM"],
                    rows, aligns=["l", "l", "r", "r", "r", "r"])
        y -= 18
        d.text(L, y, f"TOTAL: {p['total_packages']} {s['totals']['package_type']}    "
                     f"N/W {fmt_num(p['total_net_weight_kg'])} KGS    "
                     f"G/W {fmt_num(p['total_gross_weight_kg'])} KGS    "
                     f"MEAS. {fmt_num(p['total_cbm'], 3)} CBM", size=9, bold=True)
        d.text(L, y - 22, "MARKS: " + " / ".join(p["shipping_marks"]), size=8)
    d.save()


def render_co(path: Path, s: dict, p: dict, variant: str):
    d = Doc(path, f"Certificate of Origin {p['certificate_no']}")
    L, R = MARGIN, PAGE_W - MARGIN
    mid = (L + R) / 2
    top = PAGE_H - MARGIN
    # 발급 기관·발급국은 수출국(정답) 기준. 오류 세트에서 바뀌는 것은 '원산지' 칸뿐이다.
    issued_in = s["country_of_origin"]
    issuer = f"{issued_in} EXPORT CERTIFICATION OFFICE (FICTIONAL)"

    def hs(v):
        return f"{v[:4]}.{v[4:]}" if v else ""

    if variant == "A":
        y = top
        d.box(L, y, mid - L, 64, "1. Exporter (name, address, country)", _addr_lines(s["shipper"]))
        d.box(mid, y, R - mid, 64, "Certificate No.", [p["certificate_no"]], size=11)
        y -= 64
        d.box(L, y, mid - L, 64, "2. Consignee (name, address, country)", _addr_lines(s["buyer"]))
        d.box(mid, y, R - mid, 64, "", [])
        d.ctext((mid + R) / 2, y - 26, "CERTIFICATE OF ORIGIN", size=14, bold=True)
        d.ctext((mid + R) / 2, y - 42, f"issued in {issued_in}", size=8)
        y -= 64
        d.box(L, y, mid - L, 52, "3. Means of transport and route", [p["transport"]], size=7.5)
        d.box(mid, y, R - mid, 52, "4. For official use",
              [f"Invoice No. {p['invoice_no_ref']}",
               f"dated {fmt_date(date.fromisoformat(p['invoice_date_ref']), 'iso')}"])
        y -= 64
        rows = [[str(i + 1), it["description"], hs(it["hs_code"]), f"{it['quantity']:,} {it['unit']}"]
                for i, it in enumerate(p["items"])]
        y = d.table(L, y, [40, 290, 80, 113],
                    ["5. Item No.", "6. Description of goods", "7. HS Code", "8. Quantity"], rows,
                    aligns=["l", "l", "l", "r"])
        y -= 24
        d.text(L, y, f"9. Country of origin: {p['country_of_origin']}", size=10, bold=True)
        y -= 30
        d.box(L, y, mid - L, 90, "10. Declaration by the exporter",
              ["The undersigned hereby declares that the above",
               "details and statements are correct and that all",
               f"the goods were produced in {p['country_of_origin']}.", "", s["shipper"]["name"]], size=7.5)
        d.box(mid, y, R - mid, 90, "11. Certification",
              ["It is hereby certified, on the basis of control",
               "carried out, that the declaration by the exporter",
               "is correct.", "", issuer,
               fmt_date(date.fromisoformat(p["issue_date"]), "iso")], size=7.5)
    else:
        d.ctext(PAGE_W / 2, top - 14, "CERTIFICATE OF ORIGIN", size=16, bold=True)
        d.ctext(PAGE_W / 2, top - 28, f"No. {p['certificate_no']}", size=9)
        y = top - 42
        d.box(L, y, R - L, 54, "Goods consigned from (Exporter's business name, address, country)",
              _addr_lines(s["shipper"]))
        y -= 54
        d.box(L, y, R - L, 54, "Goods consigned to (Consignee's name, address, country)",
              _addr_lines(s["buyer"]))
        y -= 54
        d.box(L, y, R - L, 34, "Transport details", [p["transport"]], size=8)
        y -= 46
        rows = [[str(i + 1), it["description"], hs(it["hs_code"]), p["country_of_origin"],
                 f"{it['quantity']:,} {it['unit']}"] for i, it in enumerate(p["items"])]
        y = d.table(L, y, [30, 250, 70, 80, 93],
                    ["Item", "Description of goods", "HS Code", "Origin", "Quantity"], rows,
                    aligns=["l", "l", "l", "l", "r"])
        y -= 20
        d.text(L, y, f"Invoice No. and date: {p['invoice_no_ref']} / "
                     f"{fmt_date(date.fromisoformat(p['invoice_date_ref']), 'dmy_slash')}", size=8.5)
        y -= 30
        d.box(L, y, R - L, 70, "Certification",
              [f"It is hereby certified that the goods described above originate in {p['country_of_origin']}.",
               "", issuer, f"Place and date: {fmt_date(date.fromisoformat(p['issue_date']), 'dmy_slash')}"],
              size=8)
    d.save()


RENDERERS = {
    "bill_of_lading": ("bl.pdf", render_bl),
    "commercial_invoice": ("invoice.pdf", render_invoice),
    "packing_list": ("packing_list.pdf", render_packing_list),
    "certificate_of_origin": ("certificate_of_origin.pdf", render_co),
}


# ---------------------------------------------------------------------------
# 5) 사진처럼 보이는 스캔본 (일부 세트)
# ---------------------------------------------------------------------------
def make_scans(set_dir: Path, rng: random.Random) -> list[str]:
    import pymupdf
    from PIL import Image, ImageFilter

    made = []
    scan_dir = set_dir / "scans"
    scan_dir.mkdir(exist_ok=True)
    for fname, _ in RENDERERS.values():
        doc = pymupdf.open(set_dir / fname)
        pix = doc[0].get_pixmap(dpi=140)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
        doc.close()
        img = img.rotate(rng.uniform(-2.5, 2.5), expand=True, fillcolor=235)
        noise = Image.effect_noise(img.size, 18)
        img = Image.blend(img, noise, 0.08).filter(ImageFilter.GaussianBlur(0.6))
        out = scan_dir / fname.replace(".pdf", ".jpg")
        img.save(out, quality=72)
        made.append(str(out.relative_to(set_dir)).replace("\\", "/"))
    return made


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-date", default=date.today().isoformat())
    ap.add_argument("--seed", type=int, default=20261120)
    ap.add_argument("--scan-sets", default="1,4,11,12", help="스캔본을 만들 세트 번호")
    args = ap.parse_args()

    base_date = date.fromisoformat(args.base_date)
    rng = random.Random(args.seed)
    scan_sets = {int(x) for x in args.scan_sets.split(",") if x}

    sets_dir = OUT / "sets"
    sets_dir.mkdir(parents=True, exist_ok=True)
    # 폴더 자체는 두고 안의 세트만 지운다 (Windows에서 열린 폴더 삭제 오류 방지)
    for child in sets_dir.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()

    manifest = []
    for n, plan in enumerate(SET_PLANS, start=1):
        s = build_shipment(n, plan, rng, base_date)
        printed = printed_fields(s)
        injected = apply_errors(s, printed, plan.get("errors", []))
        variants = {doc: ("A" if (n + i) % 2 else "B") for i, doc in enumerate(RENDERERS)}

        set_dir = sets_dir / s["set_id"]
        set_dir.mkdir()
        files = {}
        for doc, (fname, fn) in RENDERERS.items():
            fn(set_dir / fname, s, printed[doc], variants[doc])
            files[doc] = fname
        # 오류 세트는 정정된 서류도 만든다 (데모: 정정 요청 → 수정본 재업로드 → 통과)
        corrected = {}
        if injected:
            (set_dir / "corrected").mkdir()
            clean = corrected_fields(s)
            for doc, (fname, fn) in RENDERERS.items():
                fn(set_dir / "corrected" / fname, s, clean[doc], variants[doc])
                corrected[doc] = f"corrected/{fname}"
        scans = make_scans(set_dir, rng) if n in scan_sets else []

        truth = {
            "set_id": s["set_id"],
            "scenario": "error" if injected else "normal",
            "generated_with": {"seed": args.seed, "base_date": args.base_date},
            "template_variants": variants,
            "files": files,
            "corrected_files": corrected,
            "scans": scans,
            "shipment_truth": s,
            "printed_fields": printed,
            "injected_errors": injected,
            "expected_findings": expected_findings(s, injected),
        }
        (set_dir / "ground_truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")
        manifest.append({
            "set_id": s["set_id"], "scenario": truth["scenario"],
            "supplier": s["shipper"]["name"], "buyer": s["buyer"]["name"],
            "items": " + ".join(ITEMS[k]["description"] for k in plan["items"]),
            "incoterms": s["incoterms"], "bl_no": s["bl_no"], "invoice_no": s["invoice_no"],
            "containers": " ".join(c["container_no"] for c in s["containers"]),
            "injected_errors": ", ".join(e["error_type"] for e in injected),
            "expected_findings": ", ".join(f"{f['rule']}({f['severity']})" for f in truth["expected_findings"]),
            "variants": " ".join(f"{k}={v}" for k, v in variants.items()),
            "has_scans": "Y" if scans else "",
        })
        print(f"{s['set_id']}  {truth['scenario']:6}  {manifest[-1]['items'][:60]}")

    with open(OUT / "manifest.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0].keys()))
        w.writeheader()
        w.writerows(manifest)
    print(f"\n{len(manifest)}개 세트 생성 → {sets_dir}")


if __name__ == "__main__":
    main()
