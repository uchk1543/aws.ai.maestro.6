"""shipments_seed.json 을 DynamoDB 테이블에 넣는다.

테이블은 미리 만들어 둔다 (파티션 키: shipment_id, 문자열).
AWS 자격 증명은 코드에 넣지 않는다. 터미널의 AWS 프로필이나 IAM 역할을 쓴다.

실행:  python data/generator/load_to_dynamodb.py --table logistics-shipments --region <리전>
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def to_dynamo(v):
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, list):
        return [to_dynamo(x) for x in v]
    if isinstance(v, dict):
        return {k: to_dynamo(x) for k, x in v.items() if x is not None}
    return v


def main():
    import boto3

    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--region", required=True)
    ap.add_argument("--file", default=str(ROOT / "logistics" / "shipments_seed.json"))
    args = ap.parse_args()

    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)
    with table.batch_writer(overwrite_by_pkeys=["shipment_id"]) as bw:
        for row in data["shipments"]:
            bw.put_item(Item=to_dynamo(row))
    print(f"{len(data['shipments'])}건 적재 완료 → {args.table}")


if __name__ == "__main__":
    main()
