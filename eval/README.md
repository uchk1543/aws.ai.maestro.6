# eval/ 평가

규칙: .kiro/steering/agent-design.md 11번, 형식: docs/schema.md 약속 3.

| 파일 | 담당 | 내용 |
|---|---|---|
| `answers.csv` | 1번 판독 | 심은 오류 한 줄, 정상 세트는 error_type=none 한 줄 |
| `fields.csv` | 1번 판독 | 서류마다 찍힌 핵심 칸 정답 (set_id,doc,field,answer) |
| `sets.csv` | 1번 판독 | 서류 자리·형식, 품목별 HS 정답과 헷갈리는 HS |
| `queries.csv` | 1번 판독 | 현황 질문, 기대 조건, 기대 건수 |
| `score.py` | 2번 검증 | 채점 (H1·H2). 모델 호출 없이 저장된 판독으로 다시 채점 |
| `baseline.py` | 1번 판독 | 모델 단독 기준선 (H3). 상업송장·포장명세서를 한 번에 주고 불일치를 찾게 해 같은 정답지로 채점 |
| `results/baseline_dev.json` | 1번 판독 | 기준선 모델 답 (dev 75세트, 한 번). `--rescore`로 모델 호출 없이 다시 채점 |

- 정답지 CSV는 1번의 데이터셋 브랜치(`feat/dataset-kit`)에서 들어온다.
- dev로만 프롬프트와 규칙을 고친다. test(`eval/test/`)는 저장소에 올리지 않고 마지막에 한 번만 돌린다.
- 평가와 10회 반복은 확정 이력을 비운 상태에서 시작한다.
