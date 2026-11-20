"""판독 측정 채점 규칙 (samples/measure_read_all.py). 모델 호출 없음. 현장 칸 경로·맞춤 기준 (B12 #228)."""

from samples.measure_read_all import same, value_of
from tools.models import Cell, ExtractedContainer, ExtractedDocument

BL = ExtractedDocument(
    doc_type="bill_of_lading", file="bl.pdf",
    marks=Cell(raw="EXAMPLE \nDISTRIBUTION KOREA \nINC.", value="EXAMPLE DISTRIBUTION KOREA INC."),
    containers=[ExtractedContainer(line=1, seal_no=Cell(raw="EX1470293", value="EX1470293"),
                                   packages=Cell(raw="53 CTNS", value=53, unit="CTN"))],
)


def test_컨테이너_줄_경로로_값을_찾는다():
    assert value_of(BL, "containers[0].seal_no") == ("EX1470293", "EX1470293")
    assert value_of(BL, "containers[0].packages") == (53, "53 CTNS")
    assert value_of(BL, "containers[3].seal_no") == (None, None)


def test_화인은_구두점·띄어쓰기를_맞춰_비교한다():
    assert same("marks", "EXAMPLE DISTRIBUTION KOREA INC. BUSAN,KOREA", "EXAMPLE DISTRIBUTION KOREA INC. BUSAN, KOREA")
    assert not same("marks", "EXAMPLE BUSAN C/NO. 1-35", "EXAMPLE BUSAN C/NO. 1-53")
