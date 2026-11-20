"""infra/seed_shipments.py 검사 (AWS 호출 없음). 시드 파일이 Shipment 모양이고 키가 겹치지 않는지 본다."""

import importlib.util
from datetime import date
from pathlib import Path

from tools.models import Shipment

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("seed_shipments", ROOT / "infra" / "seed_shipments.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def test_seed_file_is_valid():
    shipments = seed.load(seed.seed_file())
    assert 50 <= len(shipments) <= 100


def test_to_item_uses_strings_and_drops_empty_job_id():
    s = Shipment(bl_no="BL-1", consignee="샘플무역", item="배터리", arrived_at=date(2026, 11, 17),
                 customs_status="심사 중", last_event_at=date(2026, 11, 18))
    item = seed.to_item(s)
    assert item["arrived_at"] == "2026-11-17" and "job_id" not in item
    assert Shipment.model_validate(item) == s
