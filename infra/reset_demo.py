"""데모·평가 전에 테이블을 비우고 시드를 다시 넣는다 (FB13 #170). 시험 작업 하나만 지울 수도 있다 (FB03 #160). 담당: PM. 실행: PM만.

    uv run python infra/reset_demo.py --job job-3ec5c0f3          # 그 작업이 남긴 줄만 보여 준다 (지우지 않음)
    uv run python infra/reset_demo.py --job job-3ec5c0f3 --apply  # 확인 문구를 입력하면 지운다
    uv run python infra/reset_demo.py --all                       # 처리 기록 전체를 보여 준다 (지우지 않음)
    uv run python infra/reset_demo.py --all --apply               # 확인 뒤 비우고 시드 화물 기록을 다시 넣는다
    uv run python infra/reset_demo.py --all --apply --s3          # 서류 버킷 uploads/·cache/read/도 지운다

지우는 것
    --job: team06-hs-history·team06-shipments에서 job_id가 같은 줄, team06-wms에서 키가 '#<job_id>'로 끝나는 줄, team06-jobs의 그 작업
    --all: team06-hs-history·team06-wms·team06-jobs 전체, team06-shipments에서 job_id가 있는 줄(처리한 작업이 쓴 줄).
           그다음 data/seed/shipments.json을 다시 넣는다 (미리 넣은 가상 기록 76건)
지키는 것: team06- 테이블만, 서울 리전만. 기본은 미리보기. --apply면 확인 문구('reset')를 입력받는다 (CONFIRM=reset 으로 미리 줄 수 있다).
지운 데이터는 되돌릴 수 없다. 지우기 전에 지울 줄을 build/reset-<시각>.json에 남긴다.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REGION = "ap-northeast-2"
TABLES = {"jobs": "team06-jobs", "hs": "team06-hs-history", "wms": "team06-wms", "shipments": "team06-shipments"}
KEYS = {"jobs": ("job_id",), "hs": ("importer", "item_key"), "wms": ("idempotency_key",), "shipments": ("bl_no",)}
CONFIRM_WORD = "reset"
S3_PREFIXES = ("uploads/", "cache/read/")


def plan(items: dict[str, list[dict]], *, job_ids: list[str] | None = None) -> dict[str, list[dict]]:
    """지울 줄을 고른다. 테이블을 건드리지 않는다.

    받는 것: items(테이블 별칭 → Scan한 줄 목록, 값은 파이썬 기본형), job_ids(None이면 --all).
    반환: 테이블 별칭 → 지울 줄의 키 목록.
    """
    if job_ids is None:
        return {
            "jobs": [_key("jobs", r) for r in items["jobs"]],
            "hs": [_key("hs", r) for r in items["hs"]],
            "wms": [_key("wms", r) for r in items["wms"]],
            "shipments": [_key("shipments", r) for r in items["shipments"] if r.get("job_id")],  # 시드는 job_id 칸이 없다
        }
    wanted = set(job_ids)
    return {
        "jobs": [_key("jobs", r) for r in items["jobs"] if r.get("job_id") in wanted],
        "hs": [_key("hs", r) for r in items["hs"] if r.get("job_id") in wanted],
        "wms": [_key("wms", r) for r in items["wms"] if str(r.get("idempotency_key", "")).rsplit("#", 1)[-1] in wanted],
        "shipments": [_key("shipments", r) for r in items["shipments"] if r.get("job_id") in wanted],
    }


def _key(alias: str, row: dict) -> dict:
    return {k: row[k] for k in KEYS[alias]}


def _config():
    from botocore.config import Config

    return Config(region_name=REGION, connect_timeout=5, read_timeout=5, retries={"max_attempts": 2})


def _scan(table) -> list[dict]:
    rows, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        rows += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return rows
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _confirm() -> bool:
    typed = os.environ.get("CONFIRM") or input(f"[reset] 되돌릴 수 없습니다. 계속하려면 '{CONFIRM_WORD}' 입력: ").strip()
    return typed == CONFIRM_WORD


def _backup(chosen: dict[str, list[dict]], items: dict[str, list[dict]]) -> Path:
    """지울 줄 전체를 build/에 남긴다 (되돌릴 때 손으로 다시 넣을 수 있게)."""
    keyset = {a: [json.dumps(k, sort_keys=True, default=str) for k in ks] for a, ks in chosen.items()}
    rows = {a: [r for r in items[a] if json.dumps(_key(a, r), sort_keys=True, default=str) in keyset[a]] for a in chosen}
    path = ROOT / "build" / f"reset-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="데모·평가 전 테이블 비우기 (PM만 실행)")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--job", nargs="+", metavar="JOB_ID", help="이 작업들이 남긴 줄만")
    which.add_argument("--all", action="store_true", help="처리 기록 전체 (시드 화물 기록은 다시 넣는다)")
    parser.add_argument("--apply", action="store_true", help="실제로 지운다 (없으면 미리보기)")
    parser.add_argument("--s3", action="store_true", help="--all과 함께: 서류 버킷 uploads/·cache/read/도 지운다")
    args = parser.parse_args()
    if args.s3 and not args.all:
        raise SystemExit("--s3는 --all과 함께만 쓴다")

    import boto3

    db = boto3.resource("dynamodb", config=_config())
    tables = {a: db.Table(name) for a, name in TABLES.items()}
    items = {a: _scan(t) for a, t in tables.items()}
    chosen = plan(items, job_ids=args.job)
    for alias, keys in chosen.items():
        print(f"[reset] {TABLES[alias]}: 전체 {len(items[alias])}줄 중 지울 줄 {len(keys)}")
        for k in keys[:5]:
            print(f"         {k}")
    if not args.apply:
        print("[reset] 미리보기였습니다. 지우려면 --apply")
        return
    if not _confirm():
        raise SystemExit("[reset] 확인 문구가 달라 멈춤. 아무것도 지우지 않았다")
    print(f"[reset] 지울 줄을 남김: {_backup(chosen, items).relative_to(ROOT)}")
    for alias, keys in chosen.items():
        with tables[alias].batch_writer() as batch:
            for k in keys:
                batch.delete_item(Key=k)
        print(f"[reset] {TABLES[alias]}: {len(keys)}줄 지움")
    if args.all:
        from infra.seed_shipments import load, seed_file, to_item

        shipments = load(seed_file())
        with tables["shipments"].batch_writer(overwrite_by_pkeys=["bl_no"]) as batch:
            for s in shipments:
                batch.put_item(Item=to_item(s))
        print(f"[reset] {TABLES['shipments']}: 시드 {len(shipments)}건 다시 넣음")
    if args.s3:
        account = boto3.client("sts", config=_config()).get_caller_identity()["Account"]
        bucket = boto3.resource("s3", config=_config()).Bucket(f"team06-docs-{account}")
        for prefix in S3_PREFIXES:
            gone = bucket.objects.filter(Prefix=prefix).delete()
            print(f"[reset] s3 {prefix}: {sum(len(r.get('Deleted', [])) for r in gone)}개 지움")


if __name__ == "__main__":
    main()
