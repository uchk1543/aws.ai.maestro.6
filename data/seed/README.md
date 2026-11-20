# data/seed/ 가상 화물 기록 (담당: 1번 판독, A5)

- `data/seed/shipments.json`: 가상 화물 기록 76건 (Shipment 목록). 형식은 docs/examples/shipment.json과 tools/models.py의 Shipment.
  PM이 `infra/seed_shipments.py`로 team06-shipments에 넣는다 (E2). 이 파일이 있으면 시드 스크립트가 이것을 먼저 쓴다.
- 만든 곳: `samples/make_extra.py` → `samples/data/shipments.json`을 그대로 옮겼다. 다시 만들면 두 파일을 함께 바꾼다.
- 기준일 2026-11-21(토, 데모 날). 기간은 입항일(`arrived_at`) 기준, 한국 시간.
  - 이번 주(11/16~22) 24건 중 통관 지연 3건, 지난주(11/9~15) 22건 중 통관 지연 8건
  - 현황 질문 정답지 `eval/queries.csv`의 기대 건수가 이 파일에서 나온다
- **넣는 날로 날짜를 옮긴다 (#170)**: `infra/seed_shipments.py`의 `load()`(reset_demo.py `--all`도 거침)가 모든 날짜
  (입항일·마지막 상태 변경일)를 (넣는 날 − 기준일)만큼 옮긴다 (`samples/seed_dates.py`). 그래서 평가 전·데모 직전에 **그날** 넣는다.
  - 오늘과의 거리로 정하는 질문(오늘 입항 7건, 지금 통관 지연 13건, 상태만 묻는 질문)은 어느 날이든 건수가 같다.
  - 주 경계(이번 주·지난주)와 날짜를 적은 질문(11월 2일부터 …)은 건수가 달라진다. 그날 정답표:
    `uv run python -m samples.seed_dates --today YYYY-MM-DD`, 실제 모델로 재기: `uv run python -m samples.measure_chat --today YYYY-MM-DD`
- customs_status 값: 입항 · 수입신고 · 심사 중 · 검사 중 · 수리 · 반출.
  "통관 지연" = 입항 후 3일 지나도 수리·반출 아님. 검증 담당이 E1(#29)에서 확정해 docs/schema.md에 적는다. 바뀌면 이 파일과 queries.csv를 함께 고친다.
- 가상 값만 쓴다. 회사명·B/L 번호는 실제가 아니다. `job_id`는 모두 null(미리 넣은 기록). 처리한 작업의 기록은 E3이 더한다.
