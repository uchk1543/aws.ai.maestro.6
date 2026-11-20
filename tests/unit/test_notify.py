"""확인 요청 메일 (F13 #263). 담당: 4번 서버. AWS 호출 없음 (SES는 가짜 MailSender).

api/notify.py 의 보낼 것 고르기·첨부·제목·본문·실패 처리와 ses_sender 설정을 본다.
"""
import email
import email.policy

import pytest

import api.notify as notify
from tests.unit.fakes import _client_error
from tests.unit.test_hs_request import BL, IMPORTER, NOW, docs, pending
from tools import hs_request
from tools.models import Issue, IssueCell, Job, JobResult, Step

JOB = "job-0000f013"
MISMATCH = Issue(
    rule_id="X-WT-01", grade="불일치",
    cells=[IssueCell(doc="packing_list", field="total_gross_kg", raw="6,520 KGS")],
    evidence="상업송장 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다.",
)
CHECK = Issue(rule_id="X-QT-02", grade="확인 필요", cells=[], evidence="총수량을 읽지 못했습니다.")
ENV = {"NOTIFY_FROM": "notice@example.com", "NOTIFY_TO": "owner@example.com"}
REVIEW_NOTE = "자동 생성 메일입니다. 첨부 문서를 검토한 뒤 관세사·거래처에 전달하세요."


class FakeMail:
    """SES 대신. 보낸 메일을 calls에 쌓는다. error를 주면 그 예외를 낸다."""

    def __init__(self, error: Exception | None = None):
        self.calls: list[tuple[str, str, bytes]] = []
        self.error = error

    def send(self, sender: str, to: str, raw: bytes) -> str:
        if self.error is not None:
            raise self.error
        self.calls.append((sender, to, raw))
        return "msg-1"


def job_of(*, status="waiting_approval", issues=(), hs=()) -> Job:
    return Job(job_id=JOB, status=status, result=JobResult(issues=list(issues), hs=list(hs)))


def send(job, the_docs=None, mail=None):
    mail = mail if mail is not None else FakeMail()
    step = notify.send_notice(job, docs() if the_docs is None else the_docs, IMPORTER, mail=mail, env=ENV, now=NOW)
    return step, mail


def parsed(mail: FakeMail) -> email.message.EmailMessage:
    assert len(mail.calls) == 1
    return email.message_from_bytes(mail.calls[0][2], policy=email.policy.default)


def attachments(msg) -> list[tuple[str, str, bytes]]:
    return [(a.get_filename(), a.get_content_type(), a.get_payload(decode=True)) for a in msg.iter_attachments()]


def body_of(msg) -> str:
    return msg.get_body(preferencelist=("plain",)).get_content()


def test_targets_mismatch_and_pending():
    job = job_of(issues=[MISMATCH, CHECK], hs=[pending()])
    assert notify.notice_targets(job) == ([MISMATCH], [pending()])


def test_targets_none_when_only_check_or_not_waiting():
    assert notify.notice_targets(job_of(issues=[CHECK])) == ([], [])
    assert notify.notice_targets(job_of(status="done", issues=[MISMATCH])) == ([], [])
    assert notify.notice_targets(Job(job_id=JOB, status="waiting_approval")) == ([], [])


def test_mismatch_only_attaches_notice_html():
    step, mail = send(job_of(issues=[MISMATCH]))
    [(name, kind, data)] = attachments(parsed(mail))
    assert (name, kind) == (f"notice-{BL}.html", "text/html")
    assert "X-WT-01" in data.decode("utf-8")
    assert step.ok


def test_pending_only_attaches_pdf():
    step, mail = send(job_of(hs=[pending()]))
    [(name, kind, data)] = attachments(parsed(mail))
    assert (name, kind) == (f"hs-request-{JOB}.pdf", "application/pdf")
    assert data.startswith(b"%PDF")


def test_both_one_mail_two_attachments():
    step, mail = send(job_of(issues=[MISMATCH], hs=[pending()]))
    assert [a[0] for a in attachments(parsed(mail))] == [f"notice-{BL}.html", f"hs-request-{JOB}.pdf"]
    assert step == Step(tool="send_notice", summary="담당자에게 확인 요청 메일 보냄 (불일치 1건 · HS 미확정 1개, 첨부 2개)", ok=True)
    assert mail.calls[0][:2] == ("notice@example.com", "owner@example.com")
    msg = parsed(mail)
    assert (msg["From"], msg["To"]) == ("notice@example.com", "owner@example.com")


def test_subject_uses_code_values_only():
    _, both = send(job_of(issues=[MISMATCH], hs=[pending()]))
    _, only = send(job_of(issues=[MISMATCH]))
    _, hs_only = send(job_of(hs=[pending()]))
    assert parsed(both)["Subject"] == f"[확인 요청] 작업 {JOB} · 불일치 1건 · HS 미확정 1개"
    assert parsed(only)["Subject"] == f"[확인 요청] 작업 {JOB} · 불일치 1건"
    assert parsed(hs_only)["Subject"] == f"[확인 요청] 작업 {JOB} · HS 미확정 1개"


def test_header_injection_is_ignored():
    the_docs = docs()
    bl = the_docs[2]
    the_docs[2] = bl.model_copy(update={"doc_no": bl.doc_no.model_copy(update={"raw": "BL-1\r\nBcc: evil@example.com", "value": None})})
    _, mail = send(job_of(issues=[MISMATCH]), the_docs)
    msg = parsed(mail)
    assert msg["Bcc"] is None
    assert msg["Subject"] == f"[확인 요청] 작업 {JOB} · 불일치 1건"
    assert "B/L 번호: BL-1 Bcc: evil@example.com" in body_of(msg).splitlines()  # 한 줄로 정리된 데이터


def test_body_lists_values_and_review_note():
    _, mail = send(job_of(issues=[MISMATCH, CHECK], hs=[pending()]))
    body = body_of(parsed(mail))
    for text in (REVIEW_NOTE, JOB, f"B/L 번호: {BL}", "송장 번호: QDT/26/0289", "X-WT-01", "1행 WOODEN DINING CHAIR, OAK FRAME",
                 f"notice-{BL}.html", f"hs-request-{JOB}.pdf"):
        assert text in body
    assert "X-QT-02" not in body  # 확인 필요는 첨부 문서에만 (불일치 규칙만 본문에)


def test_missing_values_are_written_as_none():
    _, mail = send(job_of(hs=[pending(name=None)]), the_docs=[])
    body = body_of(parsed(mail))
    assert "B/L 번호: 없음" in body and "송장 번호: 없음" in body and "1행 없음" in body


def test_long_document_text_is_cut():
    _, mail = send(job_of(hs=[pending(name="A" * 200)]))
    body = body_of(parsed(mail))
    assert "A" * 80 in body and "A" * 81 not in body


def test_no_config_sends_nothing():
    mail = FakeMail()
    job = job_of(issues=[MISMATCH])
    assert notify.send_notice(job, docs(), IMPORTER, mail=mail, env={}) is None
    assert notify.send_notice(job, docs(), IMPORTER, mail=mail, env={"NOTIFY_FROM": "notice@example.com"}) is None
    assert notify.send_notice(job, docs(), IMPORTER, mail=mail, env={**ENV, "NOTIFY_TO": ""}) is None
    assert mail.calls == []


def test_nothing_to_send_returns_none():
    step, mail = send(job_of(issues=[CHECK]))
    assert step is None and mail.calls == []


def test_ses_failure_returns_failed_step():
    step, _ = send(job_of(issues=[MISMATCH]), mail=FakeMail(error=_client_error("SendEmail")))
    assert step.ok is False and step.tool == "send_notice"
    assert "ClientError" in step.summary and "@" not in step.summary


def test_attachment_failure_sends_nothing(monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("글꼴 없음")

    monkeypatch.setattr(hs_request, "make_hs_request", broken)
    step, mail = send(job_of(issues=[MISMATCH], hs=[pending()]))
    assert step.ok is False and "첨부를 만들지 못함" in step.summary and "ValueError" in step.summary
    assert mail.calls == []


def test_ses_sender_config(monkeypatch):
    seen = {}

    class FakeClient:
        def send_email(self, **kwargs):
            seen["send"] = kwargs
            return {"MessageId": "msg-1"}

    def fake_client(service, **kwargs):
        seen.update(service=service, kwargs=kwargs)
        return FakeClient()

    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setattr(notify.boto3, "client", fake_client)
    sender = notify.ses_sender()
    cfg = seen["kwargs"]["config"]
    assert seen["service"] == "sesv2" and seen["kwargs"]["region_name"] == "ap-northeast-2"
    assert (cfg.connect_timeout, cfg.read_timeout) == (5, 5)
    assert cfg.retries == {"total_max_attempts": 2, "mode": "standard"}  # 처음 한 번 + 재시도 1회 (max_attempts는 재시도 횟수라 3번이 된다)
    assert sender.send("notice@example.com", "owner@example.com", b"raw") == "msg-1"
    assert seen["send"] == {
        "FromEmailAddress": "notice@example.com",
        "Destination": {"ToAddresses": ["owner@example.com"]},
        "Content": {"Raw": {"Data": b"raw"}},
    }


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_no_mail_for_unfinished_or_failed(status):
    step, mail = send(job_of(status=status, issues=[MISMATCH]))
    assert step is None and mail.calls == []
