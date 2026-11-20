"""infra/reset_demo.py의 고르기(plan) 단위 테스트. AWS 호출 없음. 담당: PM."""
from infra.reset_demo import plan

ITEMS = {
    "jobs": [{"job_id": "job-aaaa0001", "data": "{}"}, {"job_id": "job-bbbb0002", "data": "{}"}],
    "hs": [
        {"importer": "A", "item_key": "name:chair", "hs": "2620210000", "job_id": "job-aaaa0001"},
        {"importer": "B", "item_key": "name:tyre", "hs": "4011500000", "job_id": "job-bbbb0002"},
    ],
    "wms": [{"idempotency_key": "BL-1#job-aaaa0001"}, {"idempotency_key": "BL-2#job-bbbb0002"}],
    "shipments": [
        {"bl_no": "SEED-1", "customs_status": "입항"},  # 시드: job_id 칸 없음
        {"bl_no": "BL-1", "job_id": "job-aaaa0001"},
        {"bl_no": "BL-2", "job_id": "job-bbbb0002"},
    ],
}


def test_job_mode_picks_only_that_job():
    got = plan(ITEMS, job_ids=["job-aaaa0001"])
    assert got == {
        "jobs": [{"job_id": "job-aaaa0001"}],
        "hs": [{"importer": "A", "item_key": "name:chair"}],
        "wms": [{"idempotency_key": "BL-1#job-aaaa0001"}],
        "shipments": [{"bl_no": "BL-1"}],
    }


def test_all_mode_keeps_seed_shipments():
    got = plan(ITEMS)
    assert len(got["jobs"]) == 2 and len(got["hs"]) == 2 and len(got["wms"]) == 2
    assert got["shipments"] == [{"bl_no": "BL-1"}, {"bl_no": "BL-2"}]  # SEED-1은 남는다


def test_unknown_job_picks_nothing():
    assert all(v == [] for v in plan(ITEMS, job_ids=["job-ffff9999"]).values())
