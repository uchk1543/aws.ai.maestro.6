"""확인 요청 메일 (F13 #263). 담당: 서버. 처리 Lambda(api/worker.py)가 작업을 끝낼 때 부른다.

언제 쓰나: 작업이 승인 대기(waiting_approval)로 끝났는데 불일치나 HS 미확정 품목이 남았을 때.
담당자(NOTIFY_TO)에게 코드가 만든 문서를 첨부해 SES로 메일 한 통을 보낸다.
  - 불일치가 있으면 불일치 통지 문서 HTML (tools.validate.notice_document, C7 #158)
  - HS 미확정이 있으면 HS 확인 요청서 PDF (tools.hs_request.make_hs_request, X2 #260)
받는 사람은 내부 담당자다. 두 문서 모두 '사람이 검토한 뒤 전달'이라 관세사·거래처에 바로 보내지 않는다.

메일은 코드가 보낸다. 에이전트 도구가 아니고 모델을 부르지 않는다 (agent-design.md 8번).
제목·헤더에는 코드 값(작업 ID, 건수)만 넣는다. 서류에서 온 글자는 본문에만 데이터로 넣고 한 줄·80자로 자른다.
주소는 환경 변수 NOTIFY_FROM·NOTIFY_TO로만 받는다. 단계 기록·로그에는 주소를 쓰지 않는다 (화면에 보인다).
실패해도 예외를 올리지 않는다. 단계 기록 한 줄(ok=False)만 돌려주고 작업은 그대로 끝난다.
"""
import os
import re
from collections.abc import Mapping
from datetime import datetime
from email.message import EmailMessage
from email.policy import SMTP
from typing import Protocol

import boto3
from botocore.config import Config

from api import handler
from tools import hs_request, validate
from tools.models import ExtractedDocument, HSResult, Issue, Job, Step

NOTIFY_TOOL = "send_notice"
REVIEW_NOTE = "자동 생성 메일입니다. 첨부 문서를 검토한 뒤 관세사·거래처에 전달하세요."
NONE_MARK = "없음"
TEXT_LIMIT = 80  # 서류에서 온 글자 한 칸의 길이 상한
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")  # 줄바꿈·탭·제어 문자 → 공백


class MailSender(Protocol):
    """메일 보내는 곳 (tools/wms.py의 어댑터와 같은 방식). Lambda에서는 ses_sender(), 시험에서는 가짜."""

    def send(self, sender: str, to: str, raw: bytes) -> str:
        """MIME 메일(raw)을 보내고 메시지 ID를 돌려준다. 실패하면 예외를 낸다."""
        ...


class _SesSender:
    def __init__(self, client):
        self.client = client

    def send(self, sender: str, to: str, raw: bytes) -> str:
        response = self.client.send_email(
            FromEmailAddress=sender, Destination={"ToAddresses": [to]}, Content={"Raw": {"Data": raw}}
        )
        return response["MessageId"]


def ses_sender() -> MailSender:
    """SES v2로 보내는 MailSender. 서울 리전, 연결·읽기 타임아웃 5초, 재시도 1회 (team.md 외부 API)."""
    # total_max_attempts: 처음 한 번 + 재시도 1회. max_attempts는 재시도 횟수라 2로 두면 3번 부른다 (SendEmail은 멱등이 아니다)
    config = Config(connect_timeout=5, read_timeout=5, retries={"total_max_attempts": 2, "mode": "standard"})
    return _SesSender(boto3.client("sesv2", region_name=os.environ.get("AWS_REGION", "ap-northeast-2"), config=config))


def notice_targets(job: Job) -> tuple[list[Issue], list[HSResult]]:
    """메일로 알릴 것: (불일치 문제 목록, HS 미확정 품목 목록).

    언제: send_notice가 보낼지 정할 때.
    받는 것: job(작업 결과).
    반환: 승인 대기 작업이면 불일치(grade '불일치')와 HS '사람 확인 필요' 품목. 그 밖의 상태나 결과가 없으면 ([], []).
      확인 필요·참고는 세지 않는다 (화면에서 승인하면 되는 일이라 메일을 보내지 않는다).
    """
    if job.status != "waiting_approval" or job.result is None:
        return [], []
    mismatch = [i for i in job.result.issues if i.grade == "불일치"]
    return mismatch, hs_request.pending_hs(job)


def build_attachments(
    job: Job, docs: list[ExtractedDocument], importer: str | None, *, now: datetime | None = None
) -> list[tuple[str, str, bytes]]:
    """첨부 파일 목록 [(파일 이름, MIME 형식, 바이트)]. 모델·AWS 호출 없음.

    언제: send_notice가 메일을 만들기 전.
    받는 것: job(작업 결과), docs(읽은 서류), importer(수입자, HS 확인 요청서에 찍음), now(만든 시각, 시험용).
    반환: 불일치가 있으면 불일치 통지 문서 HTML(내려받기 API와 같은 이름), HS 미확정이 있으면 HS 확인 요청서 PDF.
    실패: 문서를 만들다 난 예외를 그대로 올린다 (send_notice가 단계 기록으로 바꾼다).
    """
    mismatch, pending = notice_targets(job)
    files: list[tuple[str, str, bytes]] = []
    if mismatch:
        notice = validate.notice_document(job.job_id, docs, job.result.issues)
        files.append((handler._notice_name(notice.subject, job.job_id, "html"), "text/html", notice.html.encode("utf-8")))
    if pending:
        pdf = hs_request.make_hs_request(job, docs, importer=importer, now=now)
        files.append((f"hs-request-{job.job_id}.pdf", "application/pdf", pdf))
    return files


def _one_line(text: str | None, limit: int = TEXT_LIMIT) -> str:
    """서류에서 온 글자를 본문 한 줄로: 제어 문자·줄바꿈 → 공백, 공백 하나, limit자 상한. 비었으면 '없음'."""
    cleaned = " ".join(_CONTROL.sub(" ", text or "").split())[:limit].strip()
    return cleaned or NONE_MARK


def _doc_no(docs: list[ExtractedDocument], doc_type: str) -> str | None:
    """그 종류 서류 중 처음으로 값이 있는 doc_no (적힌 그대로 raw, 없으면 푼 값)."""
    for d in docs:
        if d.doc_type == doc_type and d.doc_no is not None:
            text = d.doc_no.raw if d.doc_no.raw is not None else d.doc_no.value
            if text:
                return str(text)
    return None


def _counts(mismatch: list[Issue], pending: list[HSResult]) -> str:
    parts = []
    if mismatch:
        parts.append(f"불일치 {len(mismatch)}건")
    if pending:
        parts.append(f"HS 미확정 {len(pending)}개")
    return " · ".join(parts)


def _compose(job: Job, docs: list[ExtractedDocument], files: list[tuple[str, str, bytes]], *, sender: str, to: str) -> EmailMessage:
    """메일 한 통. 제목은 코드 값만, 본문은 일반 텍스트, 첨부는 files."""
    mismatch, pending = notice_targets(job)
    lines = [
        REVIEW_NOTE,
        "",
        f"작업: {job.job_id}",
        f"B/L 번호: {_one_line(_doc_no(docs, 'bill_of_lading'))}",
        f"송장 번호: {_one_line(_doc_no(docs, 'commercial_invoice'))}",
    ]
    if mismatch:
        rules = ", ".join(dict.fromkeys(i.rule_id for i in mismatch))
        lines.append(f"불일치: {len(mismatch)}건 ({_one_line(rules)})")
    if pending:
        lines.append(f"HS 미확정: {len(pending)}개")
        lines += [f"  - {h.line}행 {_one_line(h.item_name)}" for h in pending]
    lines.append("첨부:")
    lines += [f"  - {name}" for name, _, _ in files]

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = f"[확인 요청] 작업 {job.job_id} · {_counts(mismatch, pending)}"
    msg.set_content("\n".join(lines) + "\n")
    for name, kind, data in files:
        maintype, subtype = kind.split("/", 1)
        params = {"charset": "utf-8"} if maintype == "text" else None
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name, params=params)
    return msg


def build_message(
    job: Job, docs: list[ExtractedDocument], importer: str | None, *, sender: str, to: str, now: datetime | None = None
) -> EmailMessage:
    """확인 요청 메일 한 통을 만든다 (첨부 포함). 모델·AWS 호출 없음.

    언제: 메일 내용을 따로 보고 싶을 때 (send_notice도 같은 것을 만든다).
    받는 것: job, docs, importer, sender·to(주소), now(문서 만든 시각, 시험용).
    반환: EmailMessage. 제목 '[확인 요청] 작업 <작업 ID> · 불일치 N건 · HS 미확정 M개'(0인 쪽 뺌).
    """
    return _compose(job, docs, build_attachments(job, docs, importer, now=now), sender=sender, to=to)


def send_notice(
    job: Job,
    docs: list[ExtractedDocument],
    importer: str | None,
    *,
    mail: MailSender | None = None,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> Step | None:
    """불일치나 HS 미확정이 남은 승인 대기 작업이면 담당자에게 확인 요청 메일을 보낸다.

    언제: 처리 Lambda가 마지막 저장 직전에 한 번 (api/worker.py). HS 선택·승인·조회 때는 부르지 않는다.
    받는 것: job(끝난 작업), docs(읽은 서류), importer(수입자), mail(시험용, 없으면 ses_sender()),
      env(시험용, 없으면 os.environ. NOTIFY_FROM·NOTIFY_TO), now(문서 만든 시각, 시험용).
    반환: 보낼 것이 없거나 주소 설정이 없으면 None (설정 없음은 로그만).
      보냈으면 Step(ok=True), 첨부를 만들지 못했거나 SES가 실패하면 Step(ok=False, 오류 종류). 예외를 올리지 않는다.
    """
    mismatch, pending = notice_targets(job)
    if not mismatch and not pending:
        return None
    env = os.environ if env is None else env
    sender, to = (env.get("NOTIFY_FROM") or "").strip(), (env.get("NOTIFY_TO") or "").strip()
    print(f"[tool] send_notice job={job.job_id} 불일치={len(mismatch)} HS미확정={len(pending)}")
    if not sender or not to:
        print(f"[notify] job={job.job_id} NOTIFY_FROM·NOTIFY_TO 설정이 없어 메일을 보내지 않음")
        return None
    try:
        files = build_attachments(job, docs, importer, now=now)
    except Exception as exc:
        print(f"[error] send_notice job={job.job_id} 첨부 실패 {type(exc).__name__}: {exc}")
        return Step(tool=NOTIFY_TOOL, summary=f"확인 요청 메일 못 보냄: 첨부를 만들지 못함 ({type(exc).__name__})", ok=False)
    try:
        raw = _compose(job, docs, files, sender=sender, to=to).as_bytes(policy=SMTP)
        message_id = (mail if mail is not None else ses_sender()).send(sender, to, raw)
    except Exception as exc:
        print(f"[error] send_notice job={job.job_id} 보내기 실패 {type(exc).__name__}")
        return Step(tool=NOTIFY_TOOL, summary=f"확인 요청 메일 못 보냄: {type(exc).__name__}", ok=False)
    print(f"[notify] job={job.job_id} 보냄 message_id={message_id} 첨부 {len(files)}개")
    summary = f"담당자에게 확인 요청 메일 보냄 ({_counts(mismatch, pending)}, 첨부 {len(files)}개)"
    return Step(tool=NOTIFY_TOOL, summary=summary, ok=True)
