"""가상 화물 기록을 team06-shipments에 넣는다 (E2). 담당: PM. 실행: PM만.

    uv run python infra/seed_shipments.py              # 파일을 검사하고 넣을 건수만 보여 준다
    uv run python infra/seed_shipments.py --apply      # 실제로 넣는다 (같은 bl_no는 덮어쓴다)

파일: data/seed/shipments.json (A5)이 있으면 그것, 없으면 samples/data/shipments.json (1번 데이터셋).
한 줄 모양은 tools.models.Shipment. 테이블 칸 약속은 infra/README.md "테이블".
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.models import Shipment  # noqa: E402

TABLE = "team06-shipments"
CANDIDATES = [ROOT / "data" / "seed" / "shipments.json", ROOT / "samples" / "data" / "shipments.json"]


def seed_file() -> Path:
    """쓸 시드 파일. A5가 data/seed/에 옮겨 두면 그쪽을 쓴다."""
    for path in CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("시드 파일이 없습니다: " + ", ".join(str(p) for p in CANDIDATES))


def to_item(shipment: Shipment) -> dict[str, str]:
    """Shipment → DynamoDB 항목. 날짜는 YYYY-MM-DD 문자열, job_id가 없으면 칸을 두지 않는다."""
    item = shipment.model_dump(mode="json")
    return {k: v for k, v in item.items() if v is not None}


def load(path: Path) -> list[Shipment]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    shipments = [Shipment.model_validate(r) for r in rows]
    keys = [s.bl_no for s in shipments]
    if len(keys) != len(set(keys)):
        raise ValueError("bl_no가 겹칩니다 (테이블 키)")
    return shipments


def main() -> None:
    parser = argparse.ArgumentParser(description="가상 화물 기록을 team06-shipments에 넣는다")
    parser.add_argument("--apply", action="store_true", help="실제로 넣는다 (없으면 검사만)")
    args = parser.parse_args()

    path = seed_file()
    shipments = load(path)
    print(f"[seed] {path.relative_to(ROOT)}: {len(shipments)}건, Shipment 검사 통과")
    if not args.apply:
        print("[seed] 미리보기였습니다. 넣으려면 --apply")
        return

    import boto3

    table = boto3.resource("dynamodb", region_name="ap-northeast-2").Table(TABLE)
    with table.batch_writer(overwrite_by_pkeys=["bl_no"]) as batch:
        for s in shipments:
            batch.put_item(Item=to_item(s))
    print(f"[seed] {TABLE}에 {len(shipments)}건 넣음")


if __name__ == "__main__":
    main()
