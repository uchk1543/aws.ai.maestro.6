"""에이전트 공통 설정. 담당: 판독. 규칙: .kiro/steering/agent-design.md 10번

모델 ID는 코드에 적지 않고 환경 변수 MODEL_ID로 읽는다 (team.md).
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
REGION = os.environ.get("AWS_REGION", "ap-northeast-2")


def today_kst() -> str:
    """한국 시간 기준 오늘 날짜(YYYY-MM-DD). Lambda 시계는 UTC라 직접 계산한다."""
    return datetime.now(KST).date().isoformat()


def make_model(read_timeout: int = 120):
    """Bedrock 모델 객체를 만든다.

    언제: Strands Agent를 만들 때.
    받는 것: read_timeout(읽기 타임아웃 초. 기본 120 = 서류 한 장 판독. 현황 Agent는 API Gateway 30초 때문에 짧게, #257).
      환경 변수 MODEL_ID(필수), MAX_TOKENS(기본 8000), AWS_REGION(기본 ap-northeast-2).
    반환: strands BedrockModel.
    temperature 등 샘플링 값은 넣지 않는다 (Claude 5.5 계열에서 오류, agent-design.md 10번).
    """
    from botocore.config import Config
    from strands.models import BedrockModel

    model_id = os.environ.get("MODEL_ID")
    if not model_id:
        raise RuntimeError("환경 변수 MODEL_ID가 없습니다. 예: export MODEL_ID=<global 추론 프로필 ID>")
    return BedrockModel(
        model_id=model_id,
        region_name=REGION,
        max_tokens=int(os.environ.get("MAX_TOKENS", "8000")),
        # 읽기 타임아웃은 서류 한 장 판독 시간을 고려해 넉넉히, 재시도는 1회
        boto_client_config=Config(read_timeout=read_timeout, connect_timeout=5, retries={"max_attempts": 2, "mode": "standard"}),
    )


def text_of(message: dict) -> str:
    """응답 메시지에서 text 블록만 이어 붙인다. 위치(content[0])가 아니라 블록 종류로 읽는다."""
    return "".join(block["text"] for block in message.get("content", []) if "text" in block)
