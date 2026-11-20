"""샘플 서류와 정답지를 만든다.

입력 (generate_dataset.py 가 만든다)
  samples/data/parties.csv, items.csv, sets.csv              개발용
  samples/data/parties_test.csv, items_test.csv, sets_test.csv  발표용 (--test, git에 올리지 않음)
양식
  samples/templates/templates.xlsx  상업송장·포장명세서 (레퍼런스 기반 양식. 이 스크립트는 읽기만 한다)
  samples/render_docs.py            선하증권(B/L)·원산지증명서 그리기, 스캔본 만들기
출력
  samples/<split>/<set_id>/doc_a·doc_b (상업송장·포장명세서, 순서는 세트마다 다름), doc_c·doc_d (B/L·원산지증명서)
  eval/sets.csv, eval/fields.csv, eval/answers.csv   (발표용은 eval/test/)

이 스크립트는 값을 새로 만들지 않는다. CSV 값을 양식에 넣고, 양식과 같은 식으로 합계를 내서 서류를 그린다.
정답지는 생성기가 적은 오류(errors 칸)로 쓰고, 상업송장·포장명세서 값은 양식이 계산한 값과 맞는지 확인한다.
필요한 것: openpyxl, reportlab, pillow, numpy, LibreOffice(soffice), poppler(pdftoppm).

사용법 (저장소 맨 위에서)
  uv run --with openpyxl --with reportlab --with pillow --with numpy python samples/build_samples.py
  uv run --with openpyxl --with reportlab --with pillow --with numpy python samples/build_samples.py --only D001 D002     # 일부 세트만 (정답지는 항상 전체)
  uv run --with openpyxl --with reportlab --with pillow --with numpy python samples/build_samples.py --test               # 발표용도
"""
import argparse, csv, datetime as dt, hashlib, json, os, re, shlex, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_dataset as gen  # noqa: E402  합계 계산식(양식과 같은 식)과 HS 표기를 같이 쓴다
import render_docs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "samples/templates/templates.xlsx"
DATA = ROOT / "samples/data"
EVAL = ROOT / "eval"
DOC = {"CI": "commercial_invoice", "PL": "packing_list", "BL": "bill_of_lading", "CO": "certificate_of_origin"}
# 임시 rule_id. 관세 규칙 담당이 규칙표 v1을 정하면 여기만 바꾼다. 합계 오류(total_*)는 X-SUM-01
RULES = {"invoice_no": "X-INV-01", "total_qty": "X-QTY-01", "total_gross_kg": "X-WT-01", "total_amount": "X-SUM-01",
         "total_packages": "X-PKG-01", "container_no": "X-CNTR-01", "freight_term": "X-FRT-01",
         "hs_code": "X-HS-01", "origin_criterion": "X-OC-01", "issue_date": "X-RETRO-01", "departure_date": "X-DATE-01"}
P0_FIELDS = ("invoice_no", "total_qty", "total_gross_kg")
# 발표용 세트: 입력과 정답지를 git에 올리지 않는 곳에 따로 두고, 잠금 파일(해시)로 고정한다
TEST_SETS, EVAL_TEST, LOCK_FILE = DATA / "sets_test.csv", EVAL / "test", ROOT / "samples/test_lock.json"
DOC_SHEETS = ("CI_1", "PL_1", "CI_2", "PL_2")
DESC_REF = {"X": 1, "AK": 2, "AX": 3}           # 계산 시트의 품명 열 (desc1·desc2·desc3)
SIZE_TYPE = {"20GP": "20'GP (22G1)", "40HC": "40'HC (45G1)", "40RH": "40'RH (45R1)"}
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


def find_soffice():
    if os.environ.get("SOFFICE"):
        return shlex.split(os.environ["SOFFICE"])
    for c in ("soffice", "libreoffice"):
        if shutil.which(c):
            return [shutil.which(c)]
    mac = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    if os.path.exists(mac):
        return [mac]
    sys.exit("LibreOffice를 찾지 못했어요. 맥: brew install --cask libreoffice")


def soffice(cmd, fmt, outdir, files):
    """여러 파일을 한 번에 변환한다 (LibreOffice가 수식도 다시 계산한다)."""
    outdir.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(files), 40):
        r = subprocess.run(cmd + ["--headless", "--calc", "--convert-to", fmt, "--outdir", str(outdir)]
                           + [str(f) for f in files[i:i + 40]], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            sys.exit(f"LibreOffice 변환 실패:\n{r.stderr}")


def read_csv(name):
    if not (DATA / name).exists():
        return []
    with open(DATA / name, encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f) if (row.get(next(iter(row))) or "").strip()]


def typed(header, v):
    v = (v or "").strip()
    if v == "":
        return None
    if re.search(r"(^|_)hs", header):           # HS는 글자로 둔다 (0901.11 → 901.11 이 되지 않게)
        return v
    if header.endswith("_date"):
        return dt.date.fromisoformat(v)
    try:
        return int(v) if v.lstrip("-").isdigit() else float(v)
    except ValueError:
        return v


def fill_sheet(ws, rows):
    """양식 시트에 줄을 채운다. 양식에 없는 칸(B/L·원산지증명서 값 등)은 넣지 않는다."""
    hdr = [c.value for c in ws[1] if c.value]
    for r in range(2, ws.max_row + 1):          # 예시 줄 지우기 (서식은 남김)
        for c in range(1, len(hdr) + 1):
            ws.cell(r, c).value = None
    for r, row in enumerate(rows, 2):
        for c, h in enumerate(hdr, 1):
            ws.cell(r, c).value = typed(h, row.get(h))


def extend_calc(ws, n_sets):
    """계산 시트 수식을 세트 수만큼 아래로 늘린다. 양식에는 60세트(2~61행)까지만 있다.
    서류 시트는 계산 시트를 열 전체로 읽으므로 수식만 늘리면 된다."""
    last = 1
    while str(ws.cell(last + 1, 1).value or "").startswith("="):
        last += 1
    for r in range(last + 1, n_sets + 2):
        for c in range(1, ws.max_column + 1):
            src = ws.cell(last, c).value
            if isinstance(src, str) and src.startswith("="):
                ws.cell(r, c).value = Translator(src, origin=ws.cell(last, c).coordinate).translate_formula(
                    ws.cell(r, c).coordinate)


def desc_layout(wb):
    """서류 시트마다 품명 칸 위치와 한 줄 글자 수, 줄 높이를 잰다. {시트: {줄: (칸, 한 줄 글자 수, 줄 높이pt)}}
    한 줄 글자 수는 실제보다 적게 잡는다(행이 조금 넉넉해질 뿐 글자가 잘리지는 않게)."""
    out = {}
    for name in DOC_SHEETS:
        ws = wb[name]
        for row in ws.iter_rows():
            for c in row:
                m = isinstance(c.value, str) and re.search(r"계산!\$(X|AK|AX):", c.value)
                if not m:
                    continue
                rng = next((r for r in ws.merged_cells.ranges if c.coordinate in r), None)
                cols = range(rng.min_col, rng.max_col + 1) if rng else [c.column]
                width = sum(ws.column_dimensions[get_column_letter(i)].width or 8.43 for i in cols)
                size = float(c.font.sz or 10)
                if "courier" in (c.font.name or "").lower():          # 고정폭: 글자 하나 = 0.6em
                    cpl = int((width * 5.25 - 4) / (0.6 * size)) - 1
                else:                                                # 비례폭(Arial): 대문자 기준
                    cpl = int(width * 8.4 / size)
                out.setdefault(name, {})[DESC_REF[m.group(1)]] = (c.coordinate, cpl, size * 1.3)
    return out


def wrapped_lines(text, cpl):
    """띄어쓰기에서 줄을 바꿀 때 몇 줄이 되는지 센다."""
    lines, cur = 1, 0
    for word in str(text).split():
        if cur == 0:
            cur = len(word)
        elif cur + 1 + len(word) <= cpl:
            cur += 1 + len(word)
        else:
            lines, cur = lines + 1, len(word)
        while cur > cpl:                        # 한 줄보다 긴 낱말은 다음 줄로 넘어간다
            lines, cur = lines + 1, cur - cpl
    return lines


def fit_descriptions(ws, cells):
    """품명이 몇 줄로 꺾일지 세어 그 행을 높인다(줄바꿈도 켠다). 양식의 고정 높이로는 2~3줄만 보여 잘렸다."""
    for coord, cpl, line_h in cells.values():
        c = ws[coord]
        if not c.value:
            continue
        al = copy(c.alignment)
        al.wrap_text = True
        c.alignment = al
        need = wrapped_lines(c.value, cpl) * line_h + 4
        rd = ws.row_dimensions[c.row]
        if (rd.height or 15) < need:
            rd.height = round(need, 1)


def pdf_pages(pdf_dir):
    """한 장을 넘는 PDF. PNG는 첫 장만 그리므로, 넘치면 내용이 말없이 사라진다."""
    if not shutil.which("pdfinfo"):
        print("  주의: pdfinfo(poppler)가 없어 쪽수 검사를 건너뜀")
        return []
    over = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        m = re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout)
        if m and int(m.group(1)) > 1:
            over.append(f"{pdf.stem}({m.group(1)}쪽)")
    return over


def check(parties, items, sets):
    errs = []
    pids = {p["party_id"] for p in parties}
    codes = {i["item_code"] for i in items}
    seen = set()
    for s in sets:
        sid = s["set_id"]
        if sid in seen: errs.append(f"{sid}: set_id 중복")
        seen.add(sid)
        if s["split"] not in ("dev", "test"): errs.append(f"{sid}: split은 dev/test")
        if s["style"] not in ("1", "2"): errs.append(f"{sid}: style은 1/2")
        if s["doc_a"] not in ("CI", "PL"): errs.append(f"{sid}: doc_a는 CI/PL")
        if s["format"] not in ("pdf", "png", "scan"): errs.append(f"{sid}: format은 pdf/png/scan")
        if s.get("format_bl", "pdf") not in ("pdf", "scan"): errs.append(f"{sid}: format_bl은 pdf/scan")
        if s.get("co_form") and s["co_form"] not in render_docs.CO_TITLE: errs.append(f"{sid}: co_form은 KCFTA/AK/VK")
        if s.get("co_form") and s.get("format_co") not in ("pdf", "scan"): errs.append(f"{sid}: format_co는 pdf/scan")
        for k in ("exporter_id", "consignee_id"):
            if s[k] not in pids: errs.append(f"{sid}: {k} '{s[k]}'가 parties.csv에 없음")
        if not s["item1_code"]: errs.append(f"{sid}: item1_code 비어 있음")
        for i in (1, 2, 3):
            c = s[f"item{i}_code"]
            if c and c not in codes: errs.append(f"{sid}: item{i}_code '{c}'가 items.csv에 없음")
            if c and not s[f"item{i}_qty"]: errs.append(f"{sid}: item{i}_qty 비어 있음")
        for k in ("errors", "variants"):
            try:
                json.loads(s.get(k) or "[]")
            except json.JSONDecodeError:
                errs.append(f"{sid}: {k} 칸이 JSON이 아님")
    for i in items:
        if not i["hs10_answer"]:
            print(f"  주의: {i['item_code']}의 정답 HS(hs10_answer)가 비어 있어요")
    if errs:
        sys.exit("입력 오류:\n  " + "\n  ".join(errs))


def r2(x):
    if x in (None, ""):
        return None
    v = round(float(x), 2)
    return int(v) if v == int(v) else v


def same(a, b):
    """정답 값 비교: 숫자는 값으로, 글자는 그대로."""
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a or "") == str(b or "")


def printed_item(i):
    """서류에 찍을 품목 줄. 송장 HS 칸에는 hs_on_invoice(6자리·10자리·빈칸)를 찍고 정답 HS는 정답지에만 쓴다."""
    row = {k: v for k, v in i.items() if k != "hs_on_invoice"}
    if "hs_on_invoice" in i:
        row["hs10_answer"] = i["hs_on_invoice"]
    return row


def catalog_items(items):
    out = {}
    for i in items:
        it = dict(i)
        for k in ("unit_price_usd", "net_kg_per_unit", "units_per_ctn", "ctn_tare_kg", "cbm_per_ctn"):
            it[k] = float(it[k])
        out[it["item_code"]] = it
    return out


def set_lines(s, items):
    return [(items[s[f"item{n}_code"]], int(s[f"item{n}_qty"])) for n in (1, 2, 3) if s[f"item{n}_code"]]


def errors_of(s, key="errors"):
    return json.loads(s.get(key) or "[]")


def slots(s):
    """서류 자리: doc_a·doc_b = 상업송장·포장명세서(doc_a 칸으로 순서), doc_c·doc_d = B/L·원산지증명서(세트마다 순서가 다름)."""
    out = {"doc_a": s["doc_a"], "doc_b": "PL" if s["doc_a"] == "CI" else "CI"}
    extra = ["BL"] + (["CO"] if s.get("co_form") else [])
    if len(extra) == 2 and int(hashlib.md5(s["set_id"].encode()).hexdigest(), 16) % 2:
        extra.reverse()
    out.update(zip(("doc_c", "doc_d"), extra))
    return out


def fmt_of(s, kind):
    return {"CI": s["format"], "PL": s["format"], "BL": s.get("format_bl") or "pdf", "CO": s.get("format_co") or "pdf"}[kind]


def d_bl(iso):           # 12 SEP 2026 (운송사 양식)
    d = dt.date.fromisoformat(iso)
    return f"{d.day:02d} {MONTHS[d.month - 1]} {d.year}"


def d_kc(iso):           # SEP. 12, 2026
    d = dt.date.fromisoformat(iso)
    return f"{MONTHS[d.month - 1]}. {d.day:02d}, {d.year}"


def d_vn(iso):           # 12/09/2026 (일/월/년, 베트남 서식)
    d = dt.date.fromisoformat(iso)
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def addr(p):
    """이름, 주소, 나라, 전화. 긴 줄은 그리는 쪽(render_docs)이 칸 너비에 맞춰 꺾는다."""
    return [p["name"], p["address"], p["country"], f"TEL: {p['tel']}"]


def marks(con_name, ctns, origin):
    return [con_name, "BUSAN, KOREA", f"C/NO. 1-{ctns}", f"MADE IN {origin}"]


def bl_data(s, P, I):
    """B/L에 찍을 글자. 값은 세트(CSV)와 품목에서 양식과 같은 식으로 계산하고, errors 의 B/L 오류만 바꿔 찍는다."""
    ex, con = P[s["exporter_id"]], P[s["consignee_id"]]
    lines = set_lines(s, I)
    t = gen.totals(lines)
    e = {x["field"]: x for x in errors_of(s) if x["doc"] == "BL"}
    pk = int(e["total_packages"]["value"]) if "total_packages" in e else t["ctns"]
    gross = float(e["total_gross_kg"]["value"]) if "total_gross_kg" in e else t["gross"]
    freight = e["freight_term"]["value"] if "freight_term" in e else s["freight_term"]
    conts = [c.split("/") for c in s["bl_containers"].split("|")]
    if "container_no" in e:
        conts[0][0] = e["container_no"]["value"]
    # 총계를 바꿨으면 컨테이너 명세도 같이 바꾼다 (선적요청서의 오타가 B/L 전체에 그대로 찍힌 경우)
    if pk != t["ctns"]:
        last = conts[-1] if int(conts[-1][3]) + pk - t["ctns"] > 0 else conts[0]
        last[3] = str(int(last[3]) + pk - t["ctns"])
    if gross != t["gross"]:
        acc = 0.0
        for i, c in enumerate(conts):
            c[4] = gen.fmt_num(gen.rnd(gross - acc) if i == len(conts) - 1 else gen.rnd(float(c[4]) * gross / t["gross"]))
            acc += float(c[4])
    pol = s["port_loading"].split(",")[0]
    cy = s["bl_service"] == "CY/CY"
    importer = addr(con)
    descs = list(dict.fromkeys(it["bl_desc"] for it, _ in lines))
    hs_lines = [f"HS CODE: {it['hs10_answer'][:6]}" for it, _ in lines] if s.get("bl_show_hs") else []
    notes = list(dict.fromkeys(it["bl_note"] for it, _ in lines if it.get("bl_note")))
    shipper = addr(ex)
    if int(hashlib.md5((s["set_id"] + "n").encode()).hexdigest(), 16) % 2:   # 운송사 시스템은 문장부호를 줄여 찍기도 한다
        shipper[0] = shipper[0].replace("CO., LTD.", "CO.,LTD").replace(" (SAMPLE)", "")
    return {
        "carrier": s["carrier"], "bl_no": s["bl_no"], "booking_no": f"BK{s['bl_no'][-8:]}",
        "shipper": shipper, "consignee": [s["bl_consignee"]] if s["bl_consignee"] else importer,
        "notify": importer if s["bl_notify"] == "CONSIGNEE" else ["SAME AS CONSIGNEE"],
        "refs": [f"SHIPPER'S REF.: {s['invoice_no']}", f"P/O NO.: {s['po_no']}"],
        "clause": "RECEIVED by the Carrier from the Shipper in apparent good order and condition unless otherwise noted "
                  "herein the total number or quantity of Containers or other packages or units indicated in the box "
                  "entitled 'No. of Pkgs' for carriage from the Port of Loading to the Port of Discharge, subject to the "
                  "terms hereof. One original Bill of Lading must be surrendered duly endorsed in exchange for the Goods "
                  "or delivery order. SAMPLE TERMS FOR TESTING ONLY.",
        "agent": ["SAMPLE SHIPPING AGENCY BUSAN", "12 SAMPLE-RO, JUNG-GU, BUSAN, KOREA", "TEL: +82-51-000-0099"],
        "pre_carriage": "", "receipt": f"{pol} {'CY' if cy else 'CFS'}", "vessel": s["vessel_voyage"],
        "pol": s["port_loading"], "pod": s["port_discharge"], "delivery": f"BUSAN {'CY' if cy else 'CFS'}",
        "final_dest": "", "service": s["bl_service"],
        "marks": marks(con["name"], t["ctns"], s["origin"]),
        "packages": f"{pk:,}", "package_kind": "CARTONS",
        "description": (["SHIPPER'S LOAD, STOW AND COUNT"] if cy else []) + ["SAID TO CONTAIN:"] + descs + hs_lines
                       + notes + ["", freight, f"SHIPPED ON BOARD: {d_bl(s['sailing_date'])}"],
        "gross": f"{gross:,.3f}", "cbm": f"{t['cbm']:,.3f}",
        "containers": [f"{c[0]} / {c[1]} / {SIZE_TYPE[c[2]]} / {int(c[3]):,} CTNS / {float(c[4]):,.3f} KGS / "
                       f"{float(c[5]):,.3f} CBM" for c in conts],
        "say": f"SAY: {render_docs.words(pk)} ({pk:,}) CARTONS ONLY",
        "freight": freight, "freight_at": f"PREPAID AT {pol}" if "PREPAID" in freight else "PAYABLE AT BUSAN",
        "originals": s["bl_originals"], "issued": f"{pol}, {d_bl(s['bl_issue_date'])}",
        "onboard": f"{d_bl(s['sailing_date'])}  {s['vessel_voyage']}",
        "_fields": {"bl_no": s["bl_no"], "shipper_name": shipper[0],
                    "consignee_name": s["bl_consignee"] or con["name"],
                    "notify_name": con["name"] if s["bl_notify"] == "CONSIGNEE" else "SAME AS CONSIGNEE",
                    "vessel_voyage": s["vessel_voyage"], "port_loading": s["port_loading"],
                    "port_discharge": s["port_discharge"], "onboard_date": s["sailing_date"],
                    "container_no": " ".join(c[0] for c in conts), "total_packages": pk,
                    "total_gross_kg": r2(gross), "total_cbm": t["cbm"], "freight_term": freight,
                    # 현장 칸 (B12 #228): 화인은 줄을 공백 하나로 잇고, 컨테이너 줄은 찍은 값 그대로
                    "marks": " ".join(marks(con["name"], t["ctns"], s["origin"])),
                    **{f"containers[{i}].{name}": value for i, c in enumerate(conts) for name, value in (
                        ("container_no", c[0]), ("seal_no", c[1]), ("size_type", SIZE_TYPE[c[2]]), ("packages", int(c[3])))}},
    }


def pl_site_fields(s, k, I):
    """포장명세서 현장 칸 정답 (B12 #228). 스타일 1은 화인, 스타일 2는 품목별 포장 수(No. of Pkgs)를 찍는다.

    포장명세서에 심은 오류가 있는 세트는 양식이 고친 값으로 박스 수를 다시 계산하므로 쓰지 않는다 (정답을 지어내지 않게).
    """
    if any(e["doc"] == "PL" for e in errors_of(s) + errors_of(s, "variants")):
        return {}
    lines = set_lines(s, I)
    if str(s["style"]) == "1":
        return {"marks": " ".join(marks(k["con_name"], gen.totals(lines)["ctns"], s["origin"]))}
    return {f"items[{i}].packages": gen.line_calc(it, q)[0] for i, (it, q) in enumerate(lines)}


AGREEMENT = {"KCFTA": "Free Trade Agreement between the Republic of Korea and the People's Republic of China",
             "AK": "Rules of Origin for the ASEAN-Korea Free Trade Area",
             "VK": "Free Trade Agreement between the Republic of Korea and the Socialist Republic of Viet Nam"}
AUTHORITY = {"KCFTA": "SAMPLE CHAMBER OF INTERNATIONAL COMMERCE (FOR TESTING)",
             "AK": "SAMPLE REGIONAL IMPORT-EXPORT OFFICE (FOR TESTING)",
             "VK": "SAMPLE REGIONAL IMPORT-EXPORT OFFICE (FOR TESTING)"}


def co_data(s, P, I):
    """원산지증명서에 찍을 글자. HS는 6자리(한-중 FTA는 HS2012 코드가 있으면 그것), 원산지 기준은 세트의 co_criteria.
    errors 의 원산지증명서 오류만 바꿔 찍는다."""
    form, kc = s["co_form"], s["co_form"] == "KCFTA"
    ex, con = P[s["exporter_id"]], P[s["consignee_id"]]
    lines = set_lines(s, I)
    t = gen.totals(lines)
    crit = s["co_criteria"].split("|")
    hs = [gen.fmt_hs(gen.co_hs6(it, form), "6") for it, _ in lines]
    inv, depart = s["invoice_no"], s["sailing_date"]
    for x in errors_of(s):
        if x["doc"] != "CO":
            continue
        if x["field"] == "invoice_no":
            inv = x["value"]
        elif x["field"] == "departure_date":
            depart = x["value"]
        elif x["field"].startswith("items["):
            n = int(re.search(r"\[(\d+)\]", x["field"]).group(1))
            (hs if x["field"].endswith("hs_code") else crit)[n] = x["value"]
    typo = {int(re.search(r"\[(\d+)\]", x["field"]).group(1)): x["value"]      # V3 품명 오타 (정상 세트의 헷갈리는 차이)
            for x in errors_of(s, "variants") if x["doc"] == "CO" and x["field"].endswith("description")}
    d = d_kc if kc else d_vn
    items = []
    for n, (it, q) in enumerate(lines):
        ctns, _, gross, _ = gen.line_calc(it, q)
        desc = [f"{ctns:,} ({render_docs.words(ctns)}) CARTONS OF", typo.get(n, it["description"])]
        qty = [f"{q:,} {it['unit']}", f"G.W. {gross:,.2f} KGS"]
        if not kc:
            desc.append(f"HS CODE: {hs[n]}")
            if crit[n].startswith("RVC"):
                qty.append(f"FOB USD {gen.rnd(q * it['unit_price_usd']):,.2f}")
        items.append({"no": str(n + 1), "desc": desc, "hs": hs[n], "criterion": crit[n], "quantity": qty})
    city, retro = ex["city"], s.get("co_retro") == "1"
    fields = {"co_no": s["co_no"], "exporter_name": ex["name"], "consignee_name": con["name"],
              "invoice_no": inv, "invoice_date": s["invoice_date"], "departure_date": depart,
              "issue_date": s["co_issue_date"], "issued_retroactively": "ISSUED RETROACTIVELY" if retro else ""}
    for n in range(len(lines)):
        fields[f"items[{n}].hs_code"] = hs[n]
        fields[f"items[{n}].origin_criterion"] = crit[n]
    transport = [f"Departure date: {d(depart)}", f"Vessel's name / Voyage No.: {s['vessel_voyage']}"]
    transport += [f"Port of loading: {s['port_loading']}"] if kc else []        # AK·VK 3번 칸에는 선적항 줄이 없다
    transport += [f"Port of discharge: {s['port_discharge']}"]
    return {"form": form, "co_no": s["co_no"], "exporter": addr(ex)[:-1], "producer": ["SAME AS EXPORTER"],
            "consignee": addr(con)[:-1], "transport": transport,
            "remarks": ["ISSUED RETROACTIVELY"] if retro and kc else [], "retro": retro,
            "marks": marks(con["name"], t["ctns"], s["origin"]), "items": items,
            "invoice": [inv, d(s["invoice_date"])], "origin_country": "VIET NAM" if s["origin"] == "VIETNAM" else s["origin"],
            "importing_country": "KOREA", "agreement": AGREEMENT[form],
            "declaration_place_date": f"{city}, {d(s['co_issue_date'])}", "authority": AUTHORITY[form],
            "certified_place_date": f"{city}, {d(s['co_issue_date'])}", "_fields": fields}


def rule_of(e):
    return "X-SUM-01" if e["kind"].startswith("total_") else RULES[e["field"].split(".")[-1]]


def phase_of(e):
    return "P0" if e["doc"] in ("CI", "PL") and e["field"] in P0_FIELDS else "P1"


def write_eval(calc, sets_rows, P, I):
    """정답지 세 개를 만든다. 개발용은 eval/, 발표용은 eval/test/ (git에 올리지 않음).
    상업송장·포장명세서의 정답 값은 계산 시트(양식이 계산한 값)에서 읽고, 생성기가 적은 오류와 맞는지 확인한다."""
    hdr = [c.value for c in calc[1]]
    by_id = {}
    for r in range(2, calc.max_row + 1):
        row = {h: calc.cell(r, i + 1).value for i, h in enumerate(hdr) if h}
        if row.get("set_id"):
            by_id[row["set_id"]] = row
    outs, problems = {}, []
    for s in sets_rows:
        sid, k = s["set_id"], by_id.get(s["set_id"])
        if k is None:
            sys.exit(f"{sid}: 계산 값을 못 읽었어요")
        s_out, f_out, a_out = outs.setdefault(s["split"], ([], [], []))
        sl = slots(s)
        docs = ";".join(f"{slot}={DOC[kind]}" for slot, kind in sl.items()) + ";" + \
            ";".join(f"fmt_{slot[-1]}={fmt_of(s, kind)}" for slot, kind in sl.items()) + \
            f";style={s['style']};co_form={s.get('co_form') or 'none'}"
        lines = set_lines(s, I)
        for i, (it, _) in enumerate(lines, 1):
            s_out.append([sid, s["split"], k["con_name"], docs, i, it["description"], it["hs10_answer"], it.get("trap_hs", "")])
        calc_val = {("CI", "invoice_no"): k["ci_invoice_no"], ("PL", "invoice_no"): k["pl_invoice_no"],
                    ("CI", "total_qty"): r2(k["ci_total_qty"]), ("PL", "total_qty"): r2(k["pl_total_qty"]),
                    ("CI", "total_gross_kg"): r2(k["ci_total_gross"]), ("PL", "total_gross_kg"): r2(k["pl_total_gross"]),
                    ("CI", "total_amount"): r2(k["ci_total_amount"])}
        errs, var = errors_of(s), errors_of(s, "variants")
        touched = set()
        for e in errs + var:                                   # 생성기 값 ↔ 양식 계산 값
            key = (e["doc"], e["field"])
            if key in calc_val:
                touched.add(e["field"])
                if not same(calc_val[key], e["value"]):
                    problems.append(f"{sid}: {e['doc']} {e['field']} 양식 값 {calc_val[key]} ≠ 생성기 값 {e['value']}")
        for f in P0_FIELDS:                                    # 심지 않은 칸은 두 서류가 같아야 한다
            if f not in touched and not same(calc_val[("CI", f)], calc_val[("PL", f)]):
                problems.append(f"{sid}: 심지 않은 {f}가 상업송장 {calc_val[('CI', f)]}, 포장명세서 {calc_val[('PL', f)]}로 다름")
        for doc, pre in (("commercial_invoice", "ci"), ("packing_list", "pl")):
            f_out += [[sid, doc, "invoice_no", k[f"{pre}_invoice_no"]],
                      [sid, doc, "total_qty", k[f"{pre}_total_qty"]],
                      [sid, doc, "total_gross_kg", r2(k[f"{pre}_total_gross"])],
                      [sid, doc, "exporter_name", k["exp_name"]],
                      [sid, doc, "consignee_name", k["con_name"]]]
        f_out.append([sid, "commercial_invoice", "total_amount", r2(k["ci_total_amount"])])
        f_out += [[sid, "bill_of_lading", f, v] for f, v in bl_data(s, P, I)["_fields"].items()]
        f_out += [[sid, "packing_list", f, v] for f, v in pl_site_fields(s, k, I).items()]
        if s.get("co_form"):
            f_out += [[sid, "certificate_of_origin", f, v] for f, v in co_data(s, P, I)["_fields"].items()]
        for e in errs:
            a_out.append([sid, s["split"], DOC[e["doc"]], e["field"], e["value"], e["orig"], e["kind"], rule_of(e),
                          e["line"] or "", phase_of(e), ""])
        if not errs:
            v = var[0] if var else None
            a_out.append([sid, s["split"], DOC[v["doc"]] if v else "", v["field"] if v else "", v["value"] if v else "",
                          v["orig"] if v else "", "none", "", (v["line"] or "") if v else "", "", v["kind"] if v else ""])
    if problems:
        sys.exit("정답지와 서류 값이 어긋나요 (생성기와 양식 계산식을 확인하세요):\n  " + "\n  ".join(problems[:20]))
    counts = {}
    for split, (s_out, f_out, a_out) in outs.items():
        folder = EVAL_TEST if split == "test" else EVAL
        folder.mkdir(parents=True, exist_ok=True)
        for name, head, rows in (
                ("sets.csv", ["set_id", "split", "consignee", "docs", "line", "item", "hs_answer", "trap_hs"], s_out),
                ("fields.csv", ["set_id", "doc", "field", "answer"], f_out),
                ("answers.csv", ["set_id", "split", "doc", "field", "planted_value", "original_value", "error_type",
                                 "expected_rule_id", "line", "phase", "variant"], a_out)):
            with open(folder / name, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(head); w.writerows(rows)
        n_err = sum(1 for a in a_out if a[6] != "none")
        counts[split] = (n_err, len({a[0] for a in a_out if a[6] == "none"}), sum(1 for a in a_out if a[10]))
    return counts


def place(job):
    """만든 PDF를 제자리에 놓는다. png면 그림으로, scan이면 스캔본(글자층 없는 PDF)으로."""
    pdf, dest, slot, fmt, seed = job
    for old in dest.glob(f"{slot}.*"):                  # 형식이 바뀌어도 예전 파일이 남지 않게
        old.unlink()
    if fmt == "png":
        subprocess.run(["pdftoppm", "-r", "150", "-png", "-singlefile", str(pdf), str(dest / slot)], check=True)
    elif fmt == "scan":
        render_docs.scanify(pdf, dest / f"{slot}.pdf", seed)
    else:
        shutil.copy(pdf, dest / f"{slot}.pdf")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="이 세트만 서류를 만든다 (정답지는 항상 전체)")
    ap.add_argument("--test", action="store_true", help="발표용 세트(data/sets_test.csv)도 서류와 정답지(eval/test/)를 만든다")
    ap.add_argument("--force-test", action="store_true", help="잠긴 발표용 세트도 다시 만든다 (잠금이 깨진다)")
    args = ap.parse_args()
    cmd = find_soffice()
    if not shutil.which("pdftoppm"):
        sys.exit("pdftoppm(poppler)이 필요해요. 맥: brew install poppler")
    parties, items, sets = read_csv("parties.csv"), read_csv("items.csv"), read_csv("sets.csv")
    if args.test:
        if not TEST_SETS.exists():
            sys.exit("발표용 세트 파일이 없어요 (samples/data/sets_test.csv). 먼저 generate_dataset.py 를 돌리세요.")
        if LOCK_FILE.exists() and not args.force_test:
            sys.exit("발표용 세트가 잠겨 있어요 (samples/test_lock.json). 다시 만들면 잠금이 깨져요.")
        sets += read_csv("sets_test.csv")
        parties += read_csv("parties_test.csv")
        items += read_csv("items_test.csv")
    elif TEST_SETS.exists() and not any((ROOT / "samples/test").glob("*/doc_a.*")):
        print("  주의: 발표용 서류가 아직 없어요. 만들려면 --test")
    check(parties, items, sets)
    P, I = {p["party_id"]: p for p in parties}, catalog_items(items)
    print(f"거래처 {len(parties)}, 품목 {len(items)}, 세트 {len(sets)}")

    work = Path(tempfile.mkdtemp(prefix="samples_"))
    wb = load_workbook(TEMPLATE)
    layout = desc_layout(wb)
    extend_calc(wb["계산"], len(sets))
    fill_sheet(wb["거래처"], parties); fill_sheet(wb["품목"], [printed_item(i) for i in items]); fill_sheet(wb["세트"], sets)
    targets = [s for s in sets if not args.only or s["set_id"] in args.only]

    # 1) 세트마다 안내!C4를 바꾼 사본을 만들고 LibreOffice로 다시 계산한다
    filled = []
    for s in targets:
        wb["안내"]["C4"] = s["set_id"]
        p = work / "filled" / f"{s['set_id']}.xlsx"; p.parent.mkdir(exist_ok=True)
        wb.save(p); filled.append(p)
    if not filled:
        wb["안내"]["C4"] = sets[0]["set_id"]; p = work / "filled" / "all.xlsx"; p.parent.mkdir(exist_ok=True)
        wb.save(p); filled.append(p)
    soffice(cmd, "xlsx", work / "calc", filled)

    # 2) 정답지 (계산 시트는 C4와 무관하니 첫 파일로 충분)
    first = load_workbook(work / "calc" / filled[0].name, data_only=True)
    for split, (n_err, n_ok, n_var) in write_eval(first["계산"], sets, P, I).items():
        where = "eval/test/" if split == "test" else "eval/"
        print(f"정답지({split}): 심은 오류 {n_err}건, 정상 세트 {n_ok}개(헷갈리는 차이 {n_var}) → {where}answers.csv, fields.csv, sets.csv")

    # 3) 상업송장·포장명세서: 시트 하나만 남긴 파일 → PDF. B/L·원산지증명서: reportlab으로 바로 PDF
    singles, plan = [], []
    for s in targets:
        sl = slots(s)
        for slot, kind in sl.items():
            if kind in ("CI", "PL"):
                sheet = f"{kind}_{s['style']}"
                v = load_workbook(work / "calc" / f"{s['set_id']}.xlsx", data_only=True)
                for ws in list(v.worksheets):
                    if ws.title != sheet:
                        v.remove(ws)
                v[sheet]["K1"] = v[sheet]["K2"] = v[sheet]["K3"] = None     # 인쇄 영역 밖 확인용 칸 비우기
                fit_descriptions(v[sheet], layout[sheet])                   # 긴 품명이 잘리지 않게 행 높이
                p = work / "single" / f"{s['set_id']}__{slot}.xlsx"; p.parent.mkdir(exist_ok=True)
                v.save(p); singles.append(p)
            else:
                (work / "pdf").mkdir(exist_ok=True)
                out = work / "pdf" / f"{s['set_id']}__{slot}.pdf"
                if kind == "BL":
                    render_docs.bl_pdf(out, bl_data(s, P, I))
                else:
                    render_docs.co_pdf(out, co_data(s, P, I))
            plan.append((s, slot, kind, f"{s['set_id']}__{slot}"))
    soffice(cmd, "pdf", work / "pdf", singles)
    over = pdf_pages(work / "pdf")
    if over:
        sys.exit("서류가 한 장을 넘었어요 (품명이 길거나 줄이 많음): " + ", ".join(over))

    # 4) 제자리에 저장 (형식 바꾸기는 나눠서 돌린다)
    jobs = []
    for s, slot, kind, stem in plan:
        dest = ROOT / "samples" / s["split"] / s["set_id"]; dest.mkdir(parents=True, exist_ok=True)
        jobs.append((work / "pdf" / f"{stem}.pdf", dest, slot, fmt_of(s, kind), f"{s['set_id']}:{slot}"))
        for stale in ("doc_c", "doc_d"):                   # 원산지증명서가 없어진 세트의 예전 파일
            if stale not in slots(s):
                for old in dest.glob(f"{stale}.*"):
                    old.unlink()
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        list(pool.map(place, jobs))
    shutil.rmtree(work, ignore_errors=True)
    print(f"서류 {len(plan)}장 → " + ", ".join(f"samples/{x}" for x in sorted({s['split'] for s, *_ in plan})))
    if any(s["split"] == "test" for s in targets):
        print("발표용을 만들었어요. 확인한 뒤 check_samples.py --lock-test 로 잠그세요.")


if __name__ == "__main__":
    main()
