// 작업 내역 (#281, 옛 G10·G11 문서 분류 내역): 서류를 올린 묶음(작업)마다 한 장씩, 무엇을 올렸고 무엇을 걸러냈는지 보인다.
// 카드: 언제·B/L·수입자·상태 → 올린 서류와 분류 결과 → 걸러낸 문제(불일치·확인 필요와 근거 문장) → 다음 할 일, 작업 화면으로.
// 건수·문장·분류는 서버(GET /api/jobs?all=1)가 준 값 그대로다. 화면은 다시 세거나 분류하지 않는다.
// 대시보드에서 들어오면 주소의 거르기(#/documents?grade=불일치 등)를 그대로 서버에 넘기고 칩으로 보인다.
import { useQuery } from "@tanstack/react-query";
import { getJobHistory } from "../api";
import { Icon } from "../components/Icon";
import { GRADE_CLASS } from "../components/IssueList";
import { navigate } from "../route";
import { DOC_TYPE_KO, DOC_TYPES, type DocType, type Grade, type HistoryFilters, type JobStatus, type JobSummary } from "../types";
import { STATUS_KO } from "./JobPage";

/** 종류 이름. unknown(분류 실패 포함)은 "분류 못 함"으로 모은다. */
export const KIND_LABEL: Record<DocType, string> = { ...DOC_TYPE_KO, unknown: "분류 못 함" };

const JOB_STATUSES: JobStatus[] = ["queued", "running", "waiting_approval", "done", "failed"];
const GRADES: Grade[] = ["불일치", "확인 필요", "참고"];

/** 주소 조건 → 서버 거르기. 값 목록 밖의 값은 버린다. */
export function filtersOf(params: Record<string, string>): HistoryFilters {
  const f: HistoryFilters = {};
  if (JOB_STATUSES.includes(params.job_status as JobStatus)) f.job_status = params.job_status as JobStatus;
  if (GRADES.includes(params.grade as Grade)) f.grade = params.grade as Grade;
  if (params.rule_id && /^[A-Za-z0-9_-]{1,40}$/.test(params.rule_id)) f.rule_id = params.rule_id;
  if (params.hs === "pending") f.hs = "pending";
  if (DOC_TYPES.includes(params.type as DocType)) f.type = params.type as DocType;
  return f;
}

/** 빠르게 고르는 보기. 주소 조건으로 바꿔 다시 부른다 (대시보드 링크와 같은 조건) */
const VIEWS: { key: string; label: string; params: Record<string, string> }[] = [
  { key: "all", label: "전체", params: {} },
  { key: "mismatch", label: "불일치", params: { job_status: "waiting_approval", grade: "불일치" } },
  { key: "hs", label: "HS 고를 것", params: { job_status: "waiting_approval", hs: "pending" } },
  { key: "waiting", label: "승인 대기", params: { job_status: "waiting_approval" } },
  { key: "done", label: "끝남", params: { job_status: "done" } },
  { key: "failed", label: "실패", params: { job_status: "failed" } },
];

function sameParams(a: Record<string, string>, b: Record<string, string>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].every((k) => (a[k] ?? "") === (b[k] ?? ""));
}

/** 보기 칩으로 나타나지 않는 거르기는 칩 글자로 따로 보인다. 보기 칩과 꼭 맞으면 규칙·종류만, 아니면 모든 조건 */
function extraLabels(f: HistoryFilters, matched: boolean): string[] {
  const out: string[] = [];
  if (!matched) {
    if (f.job_status) out.push(`작업 ${STATUS_KO[f.job_status]}`);
    if (f.grade) out.push(`${f.grade}가 남은 작업`);
    if (f.hs) out.push("HS 고를 품목이 있는 작업");
  }
  if (f.rule_id) out.push(`규칙 ${f.rule_id}`);
  if (f.type) out.push(`${KIND_LABEL[f.type]} 서류가 있는 작업`);
  return out;
}

/** 할 일 한 줄 (다음 할 일 종류 → 짧은 동사). 서버의 긴 문장은 마우스를 올리면(title) 보인다 */
export const TODO_SHORT: Record<JobSummary["next_action"]["kind"], string> = {
  fix_docs: "서류 고쳐 다시 올리기",
  choose_hs: "HS 코드 고르기",
  approve: "확인하고 승인하기",
  reupload: "서류 다시 올리기",
  wait: "처리 중 · 기다리기",
  none: "없음",
};

/** 작업 카드 한 장 */
function JobCard({ job }: { job: JobSummary }) {
  const docs = job.docs ?? [];
  const first = (job.issues ?? [])[0];
  const total = job.mismatch + (job.check ?? 0);
  const clean = job.status === "done" || (job.status === "waiting_approval" && total === 0);
  return (
    <article className="hist-card" aria-label={`작업 ${job.job_id}`}>
      <header className="hist-head">
        <div className="hist-title">
          <strong>{job.bl_no ?? "B/L 번호 없음"}</strong>
          {job.consignee && <span className="hist-consignee">{job.consignee}</span>}
        </div>
        <span className={`status status-${job.status}`}>{STATUS_KO[job.status]}</span>
      </header>
      <p className="hist-meta">
        {job.created_at} · <code>{job.job_id}</code>
      </p>

      <section className="hist-block" aria-label="올린 서류">
        <h3>올린 서류 {docs.length > 0 && <span className="count">{docs.length}장</span>}</h3>
        {docs.length === 0 ? (
          <p className="empty">아직 분류한 서류가 없습니다.</p>
        ) : (
          <ul className="hist-docs">
            {docs.map((d, i) => (
              <li key={`${d.file_name}-${i}`} className={d.doc_type === "unknown" ? "hist-doc unknown" : "hist-doc"}>
                <span className="hist-doc-kind">{KIND_LABEL[d.doc_type]}</span>
                <span className="hist-doc-file">{d.file_name}</span>
                {d.classified_by === "user" && <span className="hint">직접 고름</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <dl className="hist-summary">
        <div className="hist-row" aria-label="문제">
          <dt>문제</dt>
          <dd>
            {total === 0 ? (
              <span className={clean ? "hist-clean" : "hint"}>{clean ? "없음 ✔" : "아직 대조 전"}</span>
            ) : (
              <>
                {first && (
                  <span className="hist-issue">
                    <span className={`grade ${GRADE_CLASS[first.grade]}`}>{first.grade}</span>
                    <span className="hist-evidence">{first.evidence}</span>
                  </span>
                )}
                {total > 1 && <span className="hist-more">외 {total - 1}건</span>}
              </>
            )}
          </dd>
        </div>
        <div className="hist-row" aria-label="할 일">
          <dt>할 일</dt>
          <dd className="hist-todo">
            <span className={`hist-next next-${job.next_action.kind}`} title={job.next_action.message}>
              {TODO_SHORT[job.next_action.kind]}
            </span>
            {job.next_action.kind === "fix_docs" && <span className="hint">판독 오류면 사유 적고 승인</span>}
            <button type="button" className="next-go" onClick={() => navigate(`/jobs/${encodeURIComponent(job.job_id)}`)}>
              작업 보기
            </button>
          </dd>
        </div>
      </dl>
    </article>
  );
}

export function DocHistoryPage({ params = {} }: { params?: Record<string, string> }) {
  const filters = filtersOf(params);
  const query = useQuery({ queryKey: ["job-history", filters], queryFn: () => getJobHistory(filters) });
  const items = query.data?.items ?? [];
  const total = query.data?.total ?? items.length;
  const { rule_id, type, ...viewPart } = filters;
  const active = VIEWS.find((v) => sameParams(v.params, viewPart as Record<string, string>));
  const extras = extraLabels(filters, Boolean(active));
  void rule_id;
  void type;

  return (
    <section className="dochist hist">
      <div className="dochist-side">
        <h1>작업 내역</h1>
        <p className="lead">서류를 올린 묶음마다 무엇을 올렸고, 무엇을 걸러냈는지 봅니다.</p>
        <ul className="kind-list" aria-label="보기">
          {VIEWS.map((v) => (
            <li key={v.key}>
              <button
                type="button"
                className={v === active ? "kind active" : "kind"}
                aria-pressed={v === active}
                onClick={() => navigate("/documents", v.params)}
              >
                <span>{v.label}</span>
                {v === active && query.data && <span className="kind-count">{total}건</span>}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="dochist-main">
        {extras.length > 0 && (
          <div className="filter-chips" aria-label="거르기">
            {extras.map((label) => (
              <span key={label} className="filter-chip">
                {label}
              </span>
            ))}
            <button type="button" className="filter-clear" onClick={() => navigate("/documents", {})}>
              <Icon name="close" size={16} />
              거르기 지우기
            </button>
          </div>
        )}
        <h2>
          {active?.label ?? "거른 작업"}
          {query.data && <span className="count"> {total}건</span>}
        </h2>
        {query.data && total > items.length && <p className="hint">최근 {items.length}건만 보입니다.</p>}

        {query.isPending && (
          <p className="hint" role="status">
            불러오는 중…
          </p>
        )}
        {query.error && (
          <p className="error" role="alert">
            {query.error.message}
          </p>
        )}
        {query.isSuccess && items.length === 0 && <p className="empty">조건에 맞는 작업이 없습니다.</p>}

        <div className="hist-list">
          {items.map((job) => (
            <JobCard key={job.job_id} job={job} />
          ))}
        </div>
      </div>
    </section>
  );
}
