"""draft_declaration. 담당: 검증. 규칙: .kiro/steering/agent-design.md 7번, 형식: docs/schema.md

작업: e2e-plan.md C4·C5 (P1). 칸 목록과 출처는 docs/schema.md에 먼저 적고 여기 표로 옮긴다.
"""

from tools.models import DeclarationDraft, ExtractedDocument, HSResult, Issue

# (신고서 칸 이름, 출처 "서류.칸") 목록. C4에서 채운다. 예: ("품명", "commercial_invoice.items[0].name")
# docs/schema.md '신고서 초안 칸' 표와 같다 (tests/unit/test_declaration_fields.py가 맞는지 본다). 서류 전체 칸 13개, 품목 칸 10개.
DECLARATION_FIELDS: list[tuple[str, str]] = [
    ("B/L 번호", "bill_of_lading.bl_no"),
    ("선기명", "bill_of_lading.vessel_voyage"),
    ("수입자", "commercial_invoice.consignee_name"),
    ("해외공급자", "commercial_invoice.exporter_name"),
    ("적출국", "bill_of_lading.port_loading"),
    ("총중량(kg)", "packing_list.total_gross_kg"),
    ("총포장갯수", "packing_list.total_packages"),
    ("포장종류", "packing_list"),
    ("인도조건", "commercial_invoice.incoterms"),
    ("통화", "commercial_invoice"),
    ("결제금액", "commercial_invoice.total_amount"),
    ("결제방법", "commercial_invoice.payment_term"),
    ("원산지증명서 유무", "certificate_of_origin"),
    ("품명", "commercial_invoice.items[0].name"),
    ("세번부호", "hs[0].hs_code"),
    ("수량", "commercial_invoice.items[0].qty"),
    ("단위", "commercial_invoice.items[0].qty"),
    ("순중량(kg)", "packing_list.items[0].net_kg"),
    ("단가", "commercial_invoice.items[0].unit_price"),
    ("금액", "commercial_invoice.items[0].amount"),
    ("원산지", "commercial_invoice.origin"),
    ("협정", "certificate_of_origin"),
    ("원산지결정기준", "certificate_of_origin.items[0].origin_criterion"),
]

DRAFT_NOTICE = "사람 검토 전 초안"


def draft_declaration(docs: list[ExtractedDocument], issues: list[Issue], hs: list[HSResult]) -> DeclarationDraft:
    """신고서 초안을 코드로 채운다. 모델은 쓰지 않는다.

    언제: HS 결과가 나온 뒤, 그리고 사람이 HS를 고른 뒤 다시.
    받는 것: 읽은 서류, 남은 문제, 품목별 HS 결과.
    반환: DeclarationDraft. 문제가 남은 칸과 확정 안 된 HS 칸은 비우고 blank_fields에 적는다.
    """
    print(f"[tool] draft_declaration docs={[d.doc_type for d in docs]} issues={len(issues)}")
    raise NotImplementedError("C5: 신고서 초안 (검증 담당)")
