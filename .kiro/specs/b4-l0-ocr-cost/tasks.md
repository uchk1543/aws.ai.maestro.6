# Implementation Plan: b4-l0-ocr-cost

## Overview

브랜치 `feat/b4-l0-ocr-store`. 4번 담당 파일(`tools/ocr.py`, `api/worker.py`, 그 테스트)과 `infra/`(PR만, 실행은 PM)만 고친다.

## Tasks
- [x] 1. OCR 원본 S3 저장과 같은 파일 캐시 (`tools/ocr.py` ocr_cached, `api/worker.py`) — 72486cf
- [x] 2. 리뷰 반영: 클라이언트 하나(스레드), 키에 쪽 그림 설정, 빈 결과 저장 안 함, 403 miss, reset_demo — fa9c5f4
- [x] 3. Textract 제목 줄 분류 `CLASSIFY_BY_OCR`, Textract 호출 간격(초당 1건) — bf56fdc
- [x] 4. infra: worker 캐시 권한 `policy-cache.json`, 판독 캐시 켬, `NO_CACHE`·`CLASSIFY_BY_OCR`·`TEXTRACT_TPS` 환경 변수 — 926c0fd (실행은 PM)

## Notes

나중 (지금 단계에서 코드로 만들지 않는다):
1. 선하증권 읽기를 Textract 규칙으로 (확신 기준 + Bedrock 대체). steering 변경과 1번 담당 합의가 먼저다.
2. 품목 행 규칙 읽기 (상업송장·포장명세서·원산지증명서).
3. 실제 토큰 측정: worker 로그에 Bedrock `usage`(입력·출력 토큰)를 남겨 design.md 2의 어림값을 바꾼다 (1번 `tools/extract.py`).
4. 판독 effort 낮추기 (Sonnet 5.5 기본 high → low/medium에서 정확도 비교). 1번 담당.
5. Textract 초당 한도 올리기 요청 (Service Quotas, PM). 올리면 `TEXTRACT_TPS`도 올린다.
6. `extract.py`의 S3ReadCache와 `ocr.py`의 S3OcrCache를 하나로 (리뷰 #7). 1번 담당 파일이라 따로.
