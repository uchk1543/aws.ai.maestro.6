# Requirements Document

## Introduction

파이프라인을 l0(OCR 전체 파싱) → l1(필요한 칸) → l2(핵심 칸 정합) → l3(카드)로 나눠 보라는 피드백을 받았다.
지금 코드는 l1(`read_document`), l2(`cross_check`·`reread_field`), l3(`finish_report`)가 있고, l0은 F10(#194)의 Textract OCR이 맡는다.
남은 빈틈은 세 가지다.

- 작업 줄의 `ocr` 칸은 DynamoDB 400KB 한도 때문에 서류당 600줄에서 잘린다.
- 같은 파일도 매번 Textract를 부른다. 판독 캐시는 배포 환경에서 꺼져 있다(`READ_CACHE_BUCKET` 없음).
- 서류마다 Bedrock을 두 번(분류·판독) 부르는데, Textract는 이미 매번 부르고 있다.

담당: 4번 서버. 관련: F10 (#194), 판독 캐시 B3 (#124), agent-design.md 2·4번.

## Glossary

- **l0**: 서류 한 장의 Textract 글자 줄 전체(`OcrResult`, 좌표 포함).
- **OCR 캐시**: S3 `cache/ocr/<ocr_cache_key>.json`. 키는 파일 바이트 해시와 쪽 그림 설정.
- **판독 캐시**: S3 `cache/read/` (B3, `tools/extract.py`). 같은 서류면 Bedrock 판독을 부르지 않는다.
- **Textract 분류**: 첫 쪽 위쪽의 제목 줄로 서류 종류를 고르는 것 (`classify_from_ocr`). 모델 호출 없음.

## Requirements

### Requirement 1: OCR 원본 저장과 재사용

#### Acceptance Criteria

1. THE worker SHALL 자르지 않은 OCR 결과를 S3 `cache/ocr/`에 저장한다.
2. WHEN 같은 파일 바이트가 다시 올라오면 THE worker SHALL 저장분을 쓰고 Textract를 부르지 않는다.
3. IF 저장소 오류나 깨진 저장분이 있으면 THEN THE worker SHALL Textract로 다시 OCR 하고 작업을 계속한다.
4. IF OCR 결과에 글자 줄이 없으면 THEN THE worker SHALL 저장하지 않는다.
5. WHERE `NO_CACHE=1` THE worker SHALL 저장도 재사용도 하지 않는다.

### Requirement 2: Textract 분류

#### Acceptance Criteria

1. WHERE `CLASSIFY_BY_OCR=1` THE worker SHALL 서류 종류를 Textract 제목 줄로 고른다. 기본은 끈다(팀 결정 전).
2. IF 제목이 없거나 위쪽에 없거나 두 종류 제목이 비슷하면 THEN THE worker SHALL Bedrock으로 분류한다.
3. THE Textract 분류 SHALL 개발용 서류에서 Bedrock 분류(B1 #86, 288/288)보다 나쁘지 않다.

### Requirement 3: Textract 계정 한도

#### Acceptance Criteria

1. THE worker SHALL 한 컨테이너 안에서 Textract 호출 사이를 `1 / TEXTRACT_TPS`초 이상 띄운다 (서울 동기 API 한도 초당 1건).

### Requirement 4: 판독 캐시와 읽기

#### Acceptance Criteria

1. THE 배포 SHALL worker에 `READ_CACHE_BUCKET`을 주어 같은 서류의 Bedrock 판독을 다시 부르지 않는다. 라이브 데모·반복 측정은 `NO_CACHE=1`로 끈다.
2. THE 읽기를 Textract로 옮기는 일 SHALL 측정으로 정확도를 보이고 팀이 정하기 전에는 코드로 만들지 않는다 (tasks.md 나중).
