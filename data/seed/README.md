# data/seed/ 가상 화물 기록 (담당: 발표)

- 50~100건 (A5). 한 줄 형식은 docs/examples/shipment.json과 tools/models.py의 Shipment.
- 파일: `data/seed/shipments.json` (Shipment 목록). PM이 team06-shipments에 넣는다 (E2).
- customs_status 값과 "통관 지연" 기준은 검증 담당이 docs/schema.md에 정한다 (E1). 그 값만 쓴다.
- 이번 주·지난주·통관 지연 건이 골고루 들어가게 한다. 현황 질문(eval/queries.csv)의 기대 건수가 이 파일에서 나온다.
- 가상 값만 쓴다. 실제 회사명·B/L 번호를 쓰지 않는다.
