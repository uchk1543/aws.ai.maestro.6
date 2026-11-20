"""데이터 모델. 공용 파일. 형식 기준: docs/schema.md (약속 1~3), 예시: docs/examples/

다른 파일에서 같은 모양의 클래스를 새로 만들지 않는다 (team.md).
예시 JSON과 안 맞으면 예시가 아니라 이 파일을 고친다. 고치면 단톡에 알린다.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# 값 목록 (docs/schema.md)
# ---------------------------------------------------------------------------
DocType = Literal[
    "bill_of_lading", "commercial_invoice", "packing_list", "certificate_of_origin", "unknown"
]
Unreadable = Literal["흐림", "가려짐", "칸 없음"]
JobStatus = Literal["queued", "running", "waiting_approval", "done", "failed"]
Grade = Literal["불일치", "확인 필요", "참고"]
CheckedBy = Literal["pdf_text", "textract", "model_reread", "none"]
HSStatus = Literal["자동 확정", "사람 확인 필요", "사람 확정"]
HSBy = Literal["history", "auto_match", "human"]
WmsStatus = Literal["승인 대기", "등록됨"]
WmsBy = Literal["auto", "human"]
Period = Literal["today", "this_week", "last_week", "range"]

DOC_TYPE_KO: dict[str, str] = {
    "bill_of_lading": "선하증권",
    "commercial_invoice": "상업송장",
    "packing_list": "포장명세서",
    "certificate_of_origin": "원산지증명서",
    "unknown": "알 수 없는 서류",
}


class _Strict(BaseModel):
    """약속에 없는 필드가 들어오면 실패시킨다. 예시와 모델이 어긋나는 순간 CI가 잡는다."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# 약속 1. 서류 추출 결과
# ---------------------------------------------------------------------------
class Cell(_Strict):
    """서류의 칸 하나. raw는 모델이 옮긴 글자, value·unit은 코드가 푼 값."""

    raw: str | None = Field(
        default=None,
        description="서류에 적힌 그대로의 문자열. 쉼표·단위·대소문자를 고치지 않는다. 예: '6,520.00 KGS'. 못 읽으면 null",
    )
    value: str | int | float | None = Field(
        default=None,
        description="코드가 raw를 풀어 쓴 값. 숫자 칸은 숫자(예: 6520.0), 글자 칸은 정규화한 글자. 모델이 채우지 않는다",
    )
    unit: str | None = Field(
        default=None,
        description="코드가 raw에서 뽑은 단위. 정규화한 이름을 쓴다. 예: '500 CTNS' → 'CTN'",
    )
    unreadable: Unreadable | None = Field(
        default=None,
        description="못 읽은 이유. raw·value가 null일 때만 쓴다: 흐림 · 가려짐 · 칸 없음",
    )


class ExtractedItem(_Strict):
    """품목 한 행. 칸이 없는 서류는 해당 필드를 null로 둔다."""

    line: int = Field(description="서류에 적힌 행 순서. 1부터 센다")
    item_code: Cell | None = Field(
        default=None,
        description="품목 코드 칸(Item No., Part No., Style No.). 행 번호나 HS 코드와 다르다. 예: 'BP-200'",
    )
    name: Cell | None = Field(
        default=None,
        description="품명 칸(Description of Goods). 포장 형태나 원산지 문구는 넣지 않는다. 예: 'LITHIUM-ION BATTERY PACK'",
    )
    hs_code: Cell | None = Field(
        default=None,
        description="HS 코드 칸(HS Code, H.S. No.). 품목 코드와 다르다. value는 숫자만 남긴다. 예: raw '8507.60' → value '850760'",
    )
    qty: Cell | None = Field(
        default=None,
        description="수량 칸(Quantity). 포장 개수(CTNS)인지 낱개(PCS)인지 단위를 함께 옮긴다. 예: '500 CTNS'",
    )
    gross_kg: Cell | None = Field(
        default=None,
        description="총중량 칸(Gross Weight, G.W.). 포장 포함 무게로 순중량(N.W.)과 다르다. 예: '6,520.00 KGS'",
    )
    net_kg: Cell | None = Field(
        default=None,
        description="순중량 칸(Net Weight, N.W.). 포장 뺀 무게로 총중량(G.W.)과 다르다. 예: '6,100.00 KGS'",
    )
    unit_price: Cell | None = Field(
        default=None,
        description="단가 칸(Unit Price, 상업송장). 금액(Amount)과 다르다. value는 숫자, unit은 통화. 예: 'USD 28.00'",
    )
    amount: Cell | None = Field(
        default=None,
        description="행 금액 칸(Amount, 상업송장). 단가와 다르다. value는 숫자, unit은 통화. 예: 'USD 9,828.00'",
    )
    origin_criterion: Cell | None = Field(
        default=None,
        description="원산지 기준 칸(Origin Criterion, 원산지증명서 8번). 적힌 그대로. 예: 'PSR', 'WP', 'CTC', 'RVC 40%'",
    )


class ExtractedDocument(_Strict):
    """read_document 반환값 (약속 1)."""

    doc_type: DocType = Field(description="서류 종류")
    file: str = Field(description="S3 키 또는 로컬 경로. 예: 'uploads/sample-001/packing_list.pdf'")
    doc_no: Cell | None = Field(
        default=None,
        description=(
            "서류끼리 맞춰 보는 번호. 상업송장은 송장 번호(Invoice No.), "
            "포장명세서는 그 포장명세서에 적힌 송장 번호(Invoice No., No. & Date of Invoice)로 Packing List No.가 아니다, "
            "B/L은 'B/L No.', 원산지증명서는 10번 칸(Number and date of invoices)의 송장 번호로 증명서 번호(Reference No.)가 아니다. "
            "같은 칸의 날짜는 뺀다. PO No와 다르다. 예: 'QDT/26/0289'"
        ),
    )
    items: list[ExtractedItem] = Field(default_factory=list, description="품목 행 목록")
    total_gross_kg: Cell | None = Field(
        default=None,
        description="서류 하단 합계 칸의 총중량(Total Gross Weight). 행별 총중량과 다르다. 예: 'TOTAL: 6,520.00 KGS'",
    )
    total_qty: Cell | None = Field(
        default=None,
        description=(
            "서류 하단에 합계로 찍힌 품목 수량(Quantity, Q'TY)의 합계. 행별 수량과 다르다. "
            "포장 개수의 합계(Total Packages, No. of Pkgs, SAY TOTAL ... CARTONS)는 이 칸이 아니다. "
            "합계가 찍혀 있지 않으면 줄 값을 더하지 말고 비워 둔다. 예: 'TOTAL: 2,650 PCS'"
        ),
    )
    consignee_name: Cell | None = Field(
        default=None,
        description=(
            "수하인(Consignee, 수입자) 칸의 회사 이름. 주소·전화·담당자 줄은 뺀다. Notify Party·Shipper·Exporter와 다르다. "
            "HS 확정 이력과 WMS 등록의 수입자로 쓴다 (#110). 예: 'EXAMPLE HOME LIVING CO., LTD.'"
        ),
    )
    # 남은 칸 (B2 P1 #11, #110). 칸 이름은 eval/fields.csv·docs/schema.md 신고서 표와 같다
    exporter_name: Cell | None = Field(
        default=None,
        description="수출자(Exporter, Shipper/Exporter, Seller) 칸의 회사 이름. 주소는 뺀다 (상업송장·포장명세서·원산지증명서)",
    )
    shipper_name: Cell | None = Field(default=None, description="B/L의 송하인(Shipper) 칸의 회사 이름. 주소는 뺀다")
    notify_name: Cell | None = Field(
        default=None, description="B/L의 통지처(Notify Party) 칸의 이름. 'SAME AS CONSIGNEE'처럼 적힌 그대로"
    )
    total_amount: Cell | None = Field(
        default=None, description="상업송장 합계 금액(Total Amount). value는 숫자, unit은 통화. 예: 'USD 11,130.00'"
    )
    incoterms: Cell | None = Field(
        default=None, description="상업송장 가격 조건(Terms of Delivery, Price Term, Incoterms). 예: 'FOB HO CHI MINH CITY'"
    )
    payment_term: Cell | None = Field(default=None, description="상업송장 결제 조건(Terms of Payment). 예: 'T/T 30 DAYS'")
    origin: Cell | None = Field(
        default=None, description="상업송장 원산지(Country of Origin, Origin, MADE IN ...). 적힌 그대로. 예: 'VIETNAM'"
    )
    total_packages: Cell | None = Field(
        default=None,
        description=(
            "포장 개수의 합계(Total Packages, No. of Pkgs, SAY TOTAL ... CARTONS). 품목 수량 합계(total_qty)와 다르다. "
            "value는 개수, unit은 포장 단위. 예: '535 CARTONS' (포장명세서·B/L)"
        ),
    )
    total_cbm: Cell | None = Field(default=None, description="B/L 용적 합계(Measurement, CBM). 예: '63.610'")
    vessel_voyage: Cell | None = Field(default=None, description="B/L 선명·항차(Ocean Vessel / Voy. No.). 예: 'EXAMPLE VOYAGER 236N'")
    port_loading: Cell | None = Field(default=None, description="B/L 선적항(Port of Loading). 수취지(Place of Receipt)와 다르다")
    port_discharge: Cell | None = Field(default=None, description="B/L 양륙항(Port of Discharge). 인도지(Place of Delivery)와 다르다")
    onboard_date: Cell | None = Field(
        default=None, description="B/L 본선 적재일(Shipped on Board). value는 'YYYY-MM-DD'. 예: '25 OCT 2026'"
    )
    container_no: Cell | None = Field(
        default=None, description="B/L 컨테이너 번호(Container No.). 봉인 번호(Seal No.)는 뺀다. 여러 개면 공백 하나로 잇는다"
    )
    freight_term: Cell | None = Field(default=None, description="B/L 운임 조건. 예: 'FREIGHT PREPAID', 'FREIGHT COLLECT'")
    co_no: Cell | None = Field(
        default=None, description="원산지증명서 번호(Reference No., Certificate No.). 송장 번호(doc_no)와 다르다"
    )
    issue_date: Cell | None = Field(default=None, description="원산지증명서 발급일 (발급 기관 서명 칸의 날짜). value는 'YYYY-MM-DD'")
    departure_date: Cell | None = Field(default=None, description="원산지증명서 3번 칸의 출항일(Departure date). value는 'YYYY-MM-DD'")
    invoice_date: Cell | None = Field(default=None, description="원산지증명서 10번 칸의 송장 날짜. value는 'YYYY-MM-DD'")
    issued_retroactively: Cell | None = Field(
        default=None, description="원산지증명서의 'ISSUED RETROACTIVELY' 표시(체크·도장)가 있으면 그 글자. 없으면 비운다"
    )


# 모델이 실제로 채우는 모양: raw와 못 읽은 이유만 낸다 (value는 코드가 푼다)
class RawCell(_Strict):
    """모델이 내는 칸 하나. 적힌 그대로만 옮긴다."""

    raw: str | None = Field(
        default=None,
        description="서류에 적힌 그대로의 문자열. 계산·환산·합계 맞추기를 하지 않는다. 못 읽으면 null",
    )
    unreadable: Unreadable | None = Field(
        default=None, description="raw가 null일 때만: 흐림 · 가려짐 · 칸 없음"
    )


class RawItem(_Strict):
    """모델이 내는 품목 한 행. 칸 설명은 ExtractedItem과 같다."""

    line: int = Field(description="서류에 적힌 행 순서. 1부터 센다")
    item_code: RawCell | None = Field(default=None, description=ExtractedItem.model_fields["item_code"].description)
    name: RawCell | None = Field(default=None, description=ExtractedItem.model_fields["name"].description)
    hs_code: RawCell | None = Field(default=None, description="HS 코드 칸(HS Code). 점·공백도 적힌 그대로. 예: '8507.60'")
    qty: RawCell | None = Field(default=None, description=ExtractedItem.model_fields["qty"].description)
    gross_kg: RawCell | None = Field(default=None, description=ExtractedItem.model_fields["gross_kg"].description)
    net_kg: RawCell | None = Field(default=None, description=ExtractedItem.model_fields["net_kg"].description)
    unit_price: RawCell | None = Field(default=None, description=ExtractedItem.model_fields["unit_price"].description)
    amount: RawCell | None = Field(default=None, description=ExtractedItem.model_fields["amount"].description)

    # 선택 속성 한도(12개) 때문에 새 칸은 스키마에서 필수(null 허용)로 둔다 (RawDocument와 같은 방식)
    model_config = {
        **_Strict.model_config,
        "json_schema_extra": lambda schema: schema.update(
            required=sorted({*schema.get("required", []), "unit_price", "amount"})
        ),
    }


# RawDocument에서 스키마로만 필수(null 허용)로 표시하는 칸 (#133 consignee_name과 B2 P1의 남은 칸)
RAW_REQUIRED_NEW = ("consignee_name", "exporter_name", "total_amount", "incoterms", "payment_term", "origin", "total_packages")


class RawDocument(_Strict):
    """모델이 서류 한 장을 읽은 결과. 코드가 ExtractedDocument로 바꾼다."""

    doc_no: RawCell | None = Field(default=None, description=ExtractedDocument.model_fields["doc_no"].description)
    items: list[RawItem] = Field(default_factory=list, description="품목 행 목록. 적힌 행을 빠짐없이 옮긴다")
    total_gross_kg: RawCell | None = Field(
        default=None, description=ExtractedDocument.model_fields["total_gross_kg"].description
    )
    total_qty: RawCell | None = Field(default=None, description=ExtractedDocument.model_fields["total_qty"].description)
    consignee_name: RawCell | None = Field(
        default=None, description=ExtractedDocument.model_fields["consignee_name"].description
    )
    exporter_name: RawCell | None = Field(default=None, description=ExtractedDocument.model_fields["exporter_name"].description)
    total_amount: RawCell | None = Field(default=None, description=ExtractedDocument.model_fields["total_amount"].description)
    incoterms: RawCell | None = Field(default=None, description=ExtractedDocument.model_fields["incoterms"].description)
    payment_term: RawCell | None = Field(default=None, description=ExtractedDocument.model_fields["payment_term"].description)
    origin: RawCell | None = Field(default=None, description=ExtractedDocument.model_fields["origin"].description)
    total_packages: RawCell | None = Field(
        default=None, description=ExtractedDocument.model_fields["total_packages"].description
    )

    # Bedrock 구조화 출력은 필수가 아닌 속성을 전체 12개까지만 받는다 (agent-design.md 10번).
    # 지금까지 12개라서 새 칸은 스키마에서 필수(null 허용)로 둔다. 파이썬에서는 기본값 None이라 기존 가짜 응답도 그대로 검증된다.
    model_config = {
        **_Strict.model_config,
        "json_schema_extra": lambda schema: schema.update(
            required=sorted({*schema.get("required", []), *RAW_REQUIRED_NEW})
        ),
    }


# B/L·원산지증명서는 칸이 많아 종류별 Raw 모델로 읽는다 (B2 P1). 칸은 모두 필수 + null 허용이라 선택 속성은 RawCell 둘뿐이다.
def _doc_desc(name: str) -> str:
    return ExtractedDocument.model_fields[name].description or ""


def _item_desc(name: str) -> str:
    field = RawItem.model_fields.get(name) or ExtractedItem.model_fields[name]
    return field.description or ""


class RawBillOfLading(_Strict):
    """모델이 B/L 한 장을 읽은 결과. 품목 행은 옮기지 않는다."""

    doc_no: RawCell | None = Field(description="B/L No. 칸의 번호. Booking No., Container No., 송장 번호와 다르다")
    shipper_name: RawCell | None = Field(description=_doc_desc("shipper_name"))
    consignee_name: RawCell | None = Field(description=_doc_desc("consignee_name"))
    notify_name: RawCell | None = Field(description=_doc_desc("notify_name"))
    vessel_voyage: RawCell | None = Field(description=_doc_desc("vessel_voyage"))
    port_loading: RawCell | None = Field(description=_doc_desc("port_loading"))
    port_discharge: RawCell | None = Field(description=_doc_desc("port_discharge"))
    onboard_date: RawCell | None = Field(description=_doc_desc("onboard_date"))
    container_no: RawCell | None = Field(description=_doc_desc("container_no"))
    freight_term: RawCell | None = Field(description=_doc_desc("freight_term"))
    total_packages: RawCell | None = Field(description=_doc_desc("total_packages"))
    total_gross_kg: RawCell | None = Field(
        description="Gross Weight 칸의 총중량. Measurement(CBM)와 다르다. 단위가 칸 제목에만 있으면 숫자만 옮긴다"
    )
    total_cbm: RawCell | None = Field(description=_doc_desc("total_cbm"))


class RawOriginItem(_Strict):
    """원산지증명서 품목 한 행."""

    line: int = Field(description="5번 Item number. 1부터 센다")
    name: RawCell | None = Field(description=_item_desc("name"))
    hs_code: RawCell | None = Field(description=_item_desc("hs_code"))
    qty: RawCell | None = Field(description=_item_desc("qty"))
    origin_criterion: RawCell | None = Field(description=_item_desc("origin_criterion"))


class RawOrigin(_Strict):
    """모델이 원산지증명서 한 장을 읽은 결과."""

    doc_no: RawCell | None = Field(description="10번 칸(Number and date of invoices)의 송장 번호. 증명서 번호(Reference No.)와 다르다")
    co_no: RawCell | None = Field(description=_doc_desc("co_no"))
    exporter_name: RawCell | None = Field(description=_doc_desc("exporter_name"))
    consignee_name: RawCell | None = Field(description=_doc_desc("consignee_name"))
    departure_date: RawCell | None = Field(description=_doc_desc("departure_date"))
    invoice_date: RawCell | None = Field(description=_doc_desc("invoice_date"))
    issue_date: RawCell | None = Field(description=_doc_desc("issue_date"))
    issued_retroactively: RawCell | None = Field(description=_doc_desc("issued_retroactively"))
    items: list[RawOriginItem] = Field(description="품목 행 목록. 적힌 행을 빠짐없이 옮긴다")


# 종류별 Raw 모델. 여기 없는 종류(상업송장·포장명세서)는 RawDocument로 읽는다
RAW_MODELS: dict[str, type[BaseModel]] = {
    "bill_of_lading": RawBillOfLading,
    "certificate_of_origin": RawOrigin,
}


class Classification(_Strict):
    """classify_document 결과."""

    doc_type: DocType = Field(description="서류 종류. 확신이 없으면 unknown")
    reason: str = Field(description="근거: 서류 제목, 특징이 되는 칸 이름. 예: '제목 PACKING LIST, N.W./G.W. 칸'")


# ---------------------------------------------------------------------------
# 약속 2. 작업 API
# ---------------------------------------------------------------------------
class Step(_Strict):
    """작업 단계 기록 한 줄. 화면의 진행 단계."""

    tool: str = Field(description="부른 도구 이름. 예: 'cross_check'")
    summary: str = Field(description="사람이 읽을 한 줄 요약. 예: '불일치 1건'")
    ok: bool = Field(description="도구가 오류 없이 끝났는지")


class IssueCell(_Strict):
    """문제에 걸린 칸 하나 (근거)."""

    doc: DocType = Field(description="서류 종류")
    field: str = Field(description="칸 경로. 예: 'items[0].gross_kg', 'total_gross_kg'")
    raw: str | None = Field(description="서류에 적힌 그대로의 값. 못 읽었으면 null")


class Issue(_Strict):
    """cross_check가 낸 문제 하나."""

    rule_id: str = Field(description="규칙 표의 rule_id. 예: 'X-WT-01'")
    grade: Grade = Field(description="불일치 · 확인 필요 · 참고")
    cells: list[IssueCell] = Field(description="근거가 된 칸들")
    suspect: DocType | None = Field(
        default=None, description="서류가 셋 이상일 때 다수결로 고른 다른 쪽 서류. 둘뿐이면 null"
    )
    evidence: str = Field(description="규칙의 문장틀로 코드가 만든 근거 문장")
    checked_by: CheckedBy = Field(default="none", description="두 번째 근거를 얻은 방법")


class HSCandidate(_Strict):
    """HS 후보 하나."""

    hs: str = Field(description="10자리 HSK. 예: '8507600000'")
    name: str = Field(description="HS 표의 품목명")
    reason: str = Field(description="서류의 어느 칸에 근거했는지")


class HSResult(_Strict):
    """품목 한 행의 HS 결과."""

    line: int = Field(description="품목 행 번호")
    status: HSStatus = Field(description="자동 확정 · 사람 확인 필요 · 사람 확정")
    by: HSBy | None = Field(default=None, description="확정한 경로. 확정 전이면 null")
    hs_code: str | None = Field(default=None, description="확정된 10자리 HSK. 확정 전이면 null")
    candidates: list[HSCandidate] = Field(default_factory=list, description="후보 최대 3개")
    item_name: str | None = Field(default=None, description="그 행의 품명(서류에 적힌 글자). 못 읽었으면 null. 화면이 '1행 · 품명'으로 보여 준다")
    doc_hs_code: str | None = Field(default=None, description="서류에 적힌 HS(적힌 그대로. 예: '9401.61'). 서류에 없으면 null")


class DeclarationField(_Strict):
    """신고서 초안의 칸 하나."""

    name: str = Field(description="신고서 칸 이름. 예: '품명'")
    value: str | int | float | None = Field(description="채운 값")
    source: str = Field(description="출처: 서류.칸. 예: 'commercial_invoice.items[0].name'")


class DeclarationDraft(_Strict):
    """신고서 초안 (사람 검토 전)."""

    fields: list[DeclarationField] = Field(default_factory=list, description="채운 칸")
    blank_fields: list[str] = Field(default_factory=list, description="문제가 남아 비워 둔 칸 경로")
    pdf_url: str | None = Field(default=None, description="PDF 주소. 아직 없으면 null")


class WmsState(_Strict):
    """가상 WMS 등록 상태."""

    status: WmsStatus = Field(description="승인 대기 · 등록됨")
    by: WmsBy | None = Field(default=None, description="등록한 경로. 등록 전이면 null")
    wms_id: str | None = Field(default=None, description="WMS가 준 번호. 등록 전이면 null")


class JobResult(_Strict):
    """작업 결과."""

    issues: list[Issue] = Field(default_factory=list, description="문제 목록")
    hs: list[HSResult] = Field(default_factory=list, description="품목별 HS 결과")
    declaration_draft: DeclarationDraft | None = Field(default=None, description="신고서 초안")
    wms: WmsState | None = Field(default=None, description="WMS 상태")


class Job(_Strict):
    """GET /jobs/{id} 응답."""

    job_id: str = Field(description="작업 ID. 예: 'job-7c1e'")
    status: JobStatus = Field(description="작업 상태")
    steps: list[Step] = Field(default_factory=list, description="도구 호출 기록")
    result: JobResult | None = Field(default=None, description="결과. 끝나기 전이면 null")
    error: str | None = Field(default=None, description="failed일 때 이유")


# ---------------------------------------------------------------------------
# 화물 기록과 현황 조회
# ---------------------------------------------------------------------------
class Shipment(_Strict):
    """team06-shipments 한 줄."""

    bl_no: str = Field(description="B/L 번호. 예: 'BL-2026-0001'")
    consignee: str = Field(description="수하인(수입자)")
    item: str = Field(description="대표 품명")
    arrived_at: date = Field(description="입항일 (한국 시간 기준 날짜)")
    customs_status: str = Field(description="통관 상태. 값 목록은 검증 담당이 docs/schema.md에 정한다")
    last_event_at: date = Field(description="마지막 상태 변경일")
    job_id: str | None = Field(default=None, description="이 화물을 처리한 작업 ID. 미리 넣은 기록이면 null")


class ChatFilters(_Strict):
    """모델이 질문을 바꾼 조회 조건."""

    status: str | None = Field(default=None, description="상태 조건. 예: '통관 지연'")
    period: Period | None = Field(default=None, description="today · this_week · last_week · range")
    date_from: date | None = Field(default=None, description="period가 range일 때만: 시작일. 모델은 질문에 적힌 날짜만 옮긴다")
    date_to: date | None = Field(default=None, description="period가 range일 때만: 끝일")
    unsupported: list[str] = Field(
        default_factory=list,
        description="질문에 있지만 위 칸으로 나타낼 수 없는 조건을 짧게. 예: '수하인 이그잼플유통', 'B/L 번호 EXSHSZX26003555', "
        "'상태 둘 이상: 수리, 반출'. 비어 있지 않으면 코드는 조회하지 않고 볼 수 없는 조건이라고 답한다 (#165)",
    )


class PeriodResolved(_Strict):
    """코드가 한국 시간으로 계산한 기간."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: date = Field(alias="from", description="시작일(포함)")
    to: date = Field(description="끝일(포함)")


class ChatResponse(_Strict):
    """POST /chat 응답."""

    answer: str = Field(description="답. 건수는 코드가 센 값을 쓴다")
    filters: ChatFilters = Field(description="쓴 조회 조건")
    period_resolved: PeriodResolved | None = Field(default=None, description="계산한 기간")
    rows: list[Shipment] = Field(default_factory=list, description="조회 결과")
    blocked: str | None = Field(
        default=None,
        description="막았으면 그 이유, 막지 않았으면 null. 가드레일 필터 이름(예: '프롬프트 공격') 또는 '무관한 질문'. "
        "막으면 모델·조회를 하지 않고 정해 둔 답을 준다 (E7 #152). 채팅 기록(E6 #157)이 이 값을 남긴다",
    )


ClassifiedBy = Literal["model", "user"]


class DocumentRecord(_Strict):
    """GET /documents 의 서류 한 장 (문서 분류 내역, G10 #143)."""

    job_id: str = Field(description="서류가 올라온 작업 ID")
    key: str = Field(description="S3 키. 예: 'uploads/<묶음>/1-invoice.pdf'")
    file_name: str = Field(description="키의 마지막 조각 (화면에 보이는 이름)")
    doc_type: DocType = Field(description="분류 결과. 분류 못 함·분류 실패는 unknown")
    classified_by: ClassifiedBy = Field(description="model = 에이전트가 분류, user = 올릴 때 사용자가 고름")
    reason: str = Field(description="분류 근거 (단계 기록의 classify_document 그대로). 사용자가 골랐으면 그렇게 적는다")
    doc_no: str | None = Field(default=None, description="읽은 서류 번호 raw. 읽지 않았으면 null")
    consignee: str | None = Field(default=None, description="읽은 수하인 raw. 읽지 않았으면 null")
    job_status: JobStatus = Field(description="작업 상태")
    created_at: str = Field(description="작업을 만든 시각, 한국 시간 'YYYY-MM-DD HH:MM'")


class DocumentsResponse(_Strict):
    """GET /documents 응답 (G10 #143). counts 는 전체 작업 기준 종류별 서류 수다."""

    counts: dict[DocType, int] = Field(description="종류별 서류 수. 화면은 다시 세지 않는다")
    items: list[DocumentRecord] = Field(default_factory=list, description="고른 종류의 서류, 최근 작업 먼저")
    next_cursor: str | None = Field(default=None, description="다음 쪽 커서. 마지막 쪽이면 null")


# GET /jobs/{id}/files 서류 보기 (F7 #156). 화면 web/src/types.ts JobFilesResponse(#140)에 url·content_type·fields를 더한 모양
MarkKind = Literal["title", "feature", "field"]


class DocPage(_Strict):
    """서류 한 쪽의 그림. 이미지 서류는 원본 한 장, PDF는 처리 Lambda가 그려 둔 쪽 그림 (F10 #188)."""

    url: str = Field(description="그림 주소 (미리 서명된 GET, 몇 분 뒤 만료)")
    width: int = Field(description="가로 px")
    height: int = Field(description="세로 px")


class DocMark(_Strict):
    """서류 위 표시. 위치(bbox)는 처리 Lambda가 저장한 Textract OCR 글자 줄에서 코드가 찾는다 (F10 #188)."""

    kind: MarkKind = Field(description="title 제목 · feature 분류 특징 칸 · field 읽은 칸")
    label: str = Field(description="보일 이름")
    text: str = Field(description="그 자리의 글자")
    field: str | None = Field(default=None, description="kind=field일 때 칸 경로. IssueCell.field와 같은 이름")
    page: int = Field(description="쪽 번호. 1부터")
    bbox: list[float] = Field(description="left, top, width, height (0~1 비율) 네 개")


class ReadField(_Strict):
    """읽은 칸 하나 (OCR 결과 표의 한 줄)."""

    field: str = Field(description="칸 경로. IssueCell.field와 같은 이름. 예: 'total_gross_kg', 'items[0].qty'")
    label: str = Field(description="한국어 칸 이름. 예: '총중량', '1행 수량'")
    raw: str | None = Field(default=None, description="서류에 적힌 그대로. 못 읽었으면 null")
    value: str | int | float | None = Field(default=None, description="코드가 푼 값")
    unit: str | None = Field(default=None, description="단위나 통화")
    unreadable: Unreadable | None = Field(default=None, description="못 읽은 이유")


class JobFileView(_Strict):
    """작업에 올라온 서류 하나의 보기 (원본 주소 + 읽은 칸)."""

    key: str = Field(description="S3 키")
    file_name: str = Field(description="키의 마지막 조각")
    doc_type: DocType = Field(description="분류 결과")
    classified_by: ClassifiedBy = Field(description="model · user")
    reason: str = Field(description="분류 근거")
    url: str = Field(description="원본 파일 주소 (미리 서명된 GET, 몇 분 뒤 만료). PDF는 iframe, 이미지는 img로 띄운다")
    content_type: str = Field(description="원본 형식. 예: 'application/pdf', 'image/png'")
    pages: list[DocPage] = Field(default_factory=list, description="쪽 그림. 이미지 서류만 한 장, PDF는 빈 목록")
    marks: list[DocMark] = Field(default_factory=list, description="서류 위 표시. OCR이나 쪽 그림이 없으면 빈 목록")
    fields: list[ReadField] = Field(default_factory=list, description="읽은 칸. 읽지 않은 서류는 빈 목록")


class JobFilesResponse(_Strict):
    """GET /jobs/{id}/files 응답."""

    files: list[JobFileView] = Field(default_factory=list, description="올린 순서")


# ---------------------------------------------------------------------------
# 역할 사이 약속 (협업 뼈대). 담당끼리 주고받는 모양이다. 바꾸면 단톡에 알린다.
# ---------------------------------------------------------------------------
class QueryResult(_Strict):
    """query_shipments 반환값. 답 문장을 뺀 ChatResponse."""

    filters: ChatFilters = Field(description="실제로 쓴 조회 조건")
    period_resolved: PeriodResolved | None = Field(default=None, description="코드가 계산한 기간")
    rule: str | None = Field(default=None, description="쓴 상태 규칙 설명. 예: '입항 후 3일 지나도 수리 안 됨'")
    rows: list[Shipment] = Field(default_factory=list, description="조회 결과")
    count: int = Field(description="코드가 센 건수")


class OcrLine(_Strict):
    """Textract가 찾은 글자 한 줄."""

    page: int = Field(description="쪽 번호. 1부터")
    text: str = Field(description="인식한 글자")
    bbox: tuple[float, float, float, float] = Field(description="위치 (left, top, width, height), 0~1 비율")


class OcrResult(_Strict):
    """ocr_document 반환값. 다시 확인(reread_field)의 두 번째 근거로 저장해 둔다."""

    file: str = Field(description="S3 키")
    lines: list[OcrLine] = Field(default_factory=list, description="글자 줄 목록")
    tables: list[list[list[str]]] = Field(default_factory=list, description="표 목록. 표 → 행 → 칸 글자")


class RereadResult(_Strict):
    """reread_field 반환값. 칸 하나를 다른 방법으로 다시 확인한 결과."""

    doc: DocType = Field(description="서류 종류")
    field: str = Field(description="칸 경로. 예: 'items[0].gross_kg'")
    first_raw: str | None = Field(description="첫 판독 raw")
    second_raw: str | None = Field(description="두 번째 근거에서 찾은 글자. 못 찾으면 null")
    checked_by: CheckedBy = Field(description="두 번째 근거를 얻은 방법")
    same: bool = Field(description="두 근거가 같은지. 같으면 불일치 확정, 다르면 '확인 필요(읽기 오류 의심)'")


class HSSearchTerms(_Strict):
    """recommend_hs 2단계: 모델이 서류에서 뽑은 검색어. HS 코드는 내지 않는다."""

    terms: list[str] = Field(description="품명·재질·용도 칸에서 뽑은 검색어. 한글·영문 동의어 포함. 예: ['리튬이온 축전지', 'lithium-ion battery']")


class HSPick(_Strict):
    """recommend_hs 4단계: 모델이 후보 안에서 고른 것."""

    picks: list[HSCandidate] = Field(description="후보 목록 안에서 고른 최대 3개, 1순위부터. 이유에는 근거 칸을 적는다")


class ReportCheck(_Strict):
    """finish_report 조건 검사 결과 (agent-design.md 1번)."""

    ok: bool = Field(description="조건을 모두 채웠는지")
    missing: list[str] = Field(default_factory=list, description="빠진 것. 예: 'packing_list.pdf 아직 안 읽음'. 에이전트가 이걸 보고 빠진 도구를 부른다")


class JobState(_Strict):
    """작업 하나를 처리하는 동안 도구들이 함께 보는 상태. 문서 처리 Agent가 들고 다닌다."""

    job_id: str = Field(description="작업 ID")
    files: list[str] = Field(description="올라온 S3 키 목록")
    doc_types: dict[str, DocType] = Field(default_factory=dict, description="S3 키 → 서류 종류 (분류 결과 또는 사용자가 고친 값)")
    docs: dict[str, ExtractedDocument] = Field(default_factory=dict, description="S3 키 → 읽은 결과")
    ocr: dict[str, OcrResult] = Field(default_factory=dict, description="S3 키 → OCR 결과")
    issues: list[Issue] = Field(default_factory=list, description="마지막 cross_check 결과 (+ 다시 확인 반영)")
    rereads: list[RereadResult] = Field(default_factory=list, description="다시 확인 결과")
    hs: list[HSResult] = Field(default_factory=list, description="품목별 HS 결과")
    declaration_draft: DeclarationDraft | None = Field(default=None, description="신고서 초안")
    steps: list[Step] = Field(default_factory=list, description="도구 호출 기록 (화면 진행 단계)")
    read_seq: int = Field(default=0, description="마지막 읽기 순번. finish_report가 '마지막 읽기 뒤 cross_check'를 검사할 때 쓴다")
    check_seq: int = Field(default=0, description="마지막 cross_check 때의 read_seq")


class WmsRecord(_Strict):
    """가상 WMS에 등록하는 한 건."""

    idempotency_key: str = Field(description="멱등 키: B/L 번호 + 작업 ID. 같은 키는 한 번만 등록")
    bl_no: str = Field(description="B/L 번호")
    job_id: str = Field(description="작업 ID")
    consignee: str = Field(description="수하인(수입자)")
    items: list[dict] = Field(default_factory=list, description="품목 (품명, 수량, 중량, 확정 HS)")
    by: WmsBy = Field(description="auto · human")
