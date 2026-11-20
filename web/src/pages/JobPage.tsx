// G3 진행 화면: GET /api/jobs/{id} 를 2초마다 불러 단계 기록(steps)을 보여 준다
// FB20: 처리가 몰리거나 시간을 넘기면 오래 대기 중에 머물 수 있어, 경과 시간과 3분이 넘으면 다시 올리라는 안내를 보인다
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError, getJob, getJobFiles } from "../api";
import { DeclarationTable } from "../components/DeclarationTable";
import { DocReview } from "../components/DocReview";
import { HsPicker } from "../components/HsPicker";
import { IssueList } from "../components/IssueList";
import { WmsPanel } from "../components/WmsPanel";
import { nextActionOf } from "../nextAction";
import { navigate } from "../route";
import type { Job, JobStatus, Step } from "../types";

export const POLL_MS = 2000;
/** 이만큼 대기·처리 중이면 다시 올리라고 안내한다 (처리 Lambda 300초, 동시 실행 5개라 몰리면 늦게 시작한다) */
export const SLOW_MS = 180_000;

/** 경과 시간 글자. 예: 72초 → "1분 12초" */
export function elapsedText(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}분 ${s % 60}초` : `${s}초`;
}

/** 이 화면을 연 뒤 지난 시간(ms). 대기·처리 중인 동안만 1초마다 다시 센다 (서버 응답에 시작 시각이 없어 화면 기준) */
function useElapsed(running: boolean): number {
  const [start] = useState(() => Date.now());
  const [now, setNow] = useState(start);
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running]);
  return now - start;
}

export const STATUS_KO: Record<JobStatus, string> = {
  queued: "대기 중",
  running: "처리 중",
  waiting_approval: "승인 대기",
  done: "끝남",
  failed: "실패",
};

/** 다음 조회까지 기다릴 시간. 처리가 끝났거나 없는 작업이면 false(멈춤). */
export function pollInterval(job: Job | undefined, error: unknown): number | false {
  if (error instanceof ApiError && error.status === 404) return false;
  if (!job) return POLL_MS;
  return job.status === "queued" || job.status === "running" ? POLL_MS : false;
}

/** 작업 화면을 나누는 다섯 단계. 한 번에 한 단계만 보이고, 처음에는 지금 할 일이 있는 단계를 연다 */
export type StageId = "process" | "review" | "hs" | "declaration" | "wms";
export const STAGES: { id: StageId; label: string }[] = [
  { id: "process", label: "처리 과정" },
  { id: "review", label: "서류 대조" },
  { id: "hs", label: "HS 코드" },
  { id: "declaration", label: "신고서 초안" },
  { id: "wms", label: "WMS 등록" },
];
type StageState = "done" | "todo" | "wait" | "fail";
const STATE_MARK: Record<StageState, string> = { done: "✔", todo: "!", wait: "…", fail: "✖" };
const STATE_KO: Record<StageState, string> = { done: "완료", todo: "할 일 있음", wait: "대기", fail: "실패" };

/** 단계마다 상태와 짧은 설명. 서버 결과로만 정한다 (다시 세지 않고 결과 목록의 길이만 본다) */
export function stageInfo(job: Job, id: StageId): { state: StageState; note: string } {
  const result = job.result;
  const running = job.status === "queued" || job.status === "running";
  if (id === "process") {
    if (job.status === "failed") return { state: "fail", note: "실패" };
    if (running) return { state: "wait", note: `${job.steps.length}단계 진행 중` };
    return { state: "done", note: `${job.steps.length}단계` };
  }
  if (!result) return { state: "wait", note: running ? "처리 뒤" : "결과 없음" };
  if (id === "review") {
    const mismatch = result.issues.filter((i) => i.grade === "불일치").length;
    const check = result.issues.filter((i) => i.grade === "확인 필요").length;
    if (mismatch) return { state: "todo", note: `불일치 ${mismatch}건` };
    if (check) return { state: "todo", note: `확인 필요 ${check}건` };
    return { state: "done", note: "문제 없음" };
  }
  if (id === "hs") {
    const pending = result.hs.filter((h) => h.status === "사람 확인 필요").length;
    if (pending) return { state: "todo", note: `${pending}개 고르기` };
    return { state: "done", note: result.hs.length ? `${result.hs.length}개 확정` : "품목 없음" };
  }
  if (id === "declaration") {
    const draft = result.declaration_draft;
    if (!draft) return { state: "wait", note: "초안 없음" };
    return { state: "done", note: draft.blank_fields.length ? `빈 칸 ${draft.blank_fields.length}개` : `${draft.fields.length}칸` };
  }
  if (result.wms?.status === "등록됨") return { state: "done", note: "등록됨" };
  if (job.status === "waiting_approval") return { state: "todo", note: "승인 대기" };
  return { state: "wait", note: "등록 전" };
}

/** 처음 열 단계: 다음 할 일이 가리키는 단계 */
export function defaultStage(job: Job): StageId {
  const kind = nextActionOf(job).kind;
  if (kind === "fix_docs") return "review";
  if (kind === "choose_hs") return "hs";
  if (kind === "approve") return "wms";
  if (kind === "none") return job.result?.wms?.status === "등록됨" ? "wms" : "review";
  return "process";
}

/** 단계 기록을 도구 이름으로 묶는다. 처리 과정을 '분류 → 읽기 → 대조 → HS → 마무리'로 나눠 보인다 */
const STEP_GROUPS: { label: string; tools: string[] }[] = [
  { label: "서류 분류", tools: ["classify_document"] },
  { label: "서류 읽기", tools: ["read_document", "ocr_document"] },
  { label: "대조와 다시 확인", tools: ["cross_check", "reread_field"] },
  { label: "HS 코드", tools: ["recommend_hs", "hs_model", "confirm_by_human"] },
];
const LAST_GROUP = "마무리";

export function groupSteps(steps: Step[]): { label: string; steps: Step[] }[] {
  const groups = [...STEP_GROUPS.map((g) => ({ label: g.label, steps: [] as Step[] })), { label: LAST_GROUP, steps: [] as Step[] }];
  for (const step of steps) {
    const i = STEP_GROUPS.findIndex((g) => g.tools.includes(step.tool));
    groups[i === -1 ? groups.length - 1 : i].steps.push(step);
  }
  return groups.filter((g) => g.steps.length > 0);
}

function StepList({ job }: { job: Job }) {
  if (job.steps.length === 0) return <p className="empty">아직 시작한 단계가 없습니다.</p>;
  const groups = groupSteps(job.steps);
  const running = job.status === "queued" || job.status === "running";
  return (
    <div className="step-groups">
      {groups.map((g, gi) => {
        const failed = g.steps.filter((s) => !s.ok).length;
        // 실패가 있거나 처리 중인 마지막 묶음은 펼쳐 둔다. 나머지는 접어 두고 요약만 보인다
        const open = failed > 0 || (running && gi === groups.length - 1);
        return (
          <details key={g.label} className={failed ? "step-group has-fail" : "step-group"} open={open}>
            <summary>
              <span className="step-group-mark" aria-hidden="true">
                {failed ? "✖" : "✔"}
              </span>
              <span className="step-group-label">{g.label}</span>
              <span className="hint">
                {g.steps.length}건{failed ? ` · 실패 ${failed}` : ""}
              </span>
            </summary>
            <ol className="steps" aria-label={`진행 단계 · ${g.label}`}>
              {g.steps.map((s, i) => (
                <li key={i} className={s.ok ? "step ok" : "step fail"}>
                  <span className="step-mark" aria-label={s.ok ? "성공" : "실패"}>
                    {s.ok ? "✔" : "✖"}
                  </span>
                  <span className="step-summary">{s.summary}</span>
                  <code className="step-tool">{s.tool}</code>
                </li>
              ))}
            </ol>
          </details>
        );
      })}
    </div>
  );
}

const NEXT_LINKS: Partial<Record<string, { label: string; stage?: StageId; path?: string }[]>> = {
  fix_docs: [
    { label: "오류 보기", stage: "review" },
    { label: "판독 오류면 승인으로", stage: "wms" },
    { label: "파일 업로드로", path: "/upload" },
  ],
  reupload: [{ label: "파일 업로드로", path: "/upload" }],
  choose_hs: [{ label: "HS 고르기로", stage: "hs" }],
  approve: [{ label: "승인 칸으로", stage: "wms" }],
};

/** 작업 화면 맨 위 '지금 상태와 다음 할 일' 한 줄 (FB22 #178). 문장은 서버 next_action 그대로 */
function NextBanner({ job, onStage }: { job: Job; onStage: (id: StageId) => void }) {
  const next = nextActionOf(job);
  const links = NEXT_LINKS[next.kind] ?? [];
  return (
    <section className={`next-action next-${next.kind}`} aria-label="다음 할 일" aria-live="polite">
      <span className="next-label">다음 할 일</span>
      <strong className="next-message">{next.message}</strong>
      {links.map((link) => (
        <button
          key={link.label}
          type="button"
          className="next-go"
          onClick={() => (link.path ? navigate(link.path) : onStage(link.stage!))}
        >
          {link.label}
        </button>
      ))}
    </section>
  );
}

/** 단계 표시줄. 결과가 나오기 전에는 처리 과정만 누를 수 있다 */
function StageBar({ job, active, onStage }: { job: Job; active: StageId; onStage: (id: StageId) => void }) {
  return (
    <div className="stage-bar" role="tablist" aria-label="작업 단계">
      {STAGES.map((stage, i) => {
        const info = stageInfo(job, stage.id);
        const selected = stage.id === active;
        return (
          <button
            key={stage.id}
            type="button"
            role="tab"
            id={`stage-tab-${stage.id}`}
            aria-selected={selected}
            aria-controls={`stage-panel-${stage.id}`}
            className={`stage stage-${info.state}${selected ? " stage-active" : ""}`}
            disabled={stage.id !== "process" && !job.result}
            onClick={() => onStage(stage.id)}
          >
            <span className="stage-mark" aria-label={STATE_KO[info.state]}>
              {STATE_MARK[info.state]}
            </span>
            <span className="stage-text">
              <span className="stage-label">
                {i + 1}. {stage.label}
              </span>
              <span className="stage-note">{info.note}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function JobPage({ jobId }: { jobId: string }) {
  const query = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId),
    refetchInterval: (q) => pollInterval(q.state.data, q.state.error),
  });
  const job = query.data;
  // G11 서류 보기: 결과가 나온 뒤 쪽 그림과 칸 위치를 받는다. 서버가 아직 주지 않으면(404·501) 글자 오류 목록만 보여 준다
  const files = useQuery({
    queryKey: ["job-files", jobId],
    queryFn: () => getJobFiles(jobId),
    enabled: Boolean(job?.result),
    retry: false,
  });
  const viewFiles = files.data?.files ?? [];
  const polling = pollInterval(job, query.error) !== false;
  const elapsed = useElapsed(polling);
  const slow = polling && Boolean(job) && elapsed >= SLOW_MS;
  // 사람이 단계를 고르면 그 단계, 아니면 지금 할 일이 있는 단계. 결과가 없으면 처리 과정만 보인다
  const [picked, setPicked] = useState<StageId | null>(null);
  const active: StageId = job && job.result ? (picked ?? defaultStage(job)) : "process";

  return (
    <section className="job">
      <h1>작업 {jobId}</h1>

      {query.isPending && <p className="hint">작업 상태를 불러오는 중…</p>}
      {query.error && !job && (
        <p className="error" role="alert">
          {query.error.message}
        </p>
      )}

      {job && (
        <>
          <p>
            <span className={`status status-${job.status}`}>{STATUS_KO[job.status]}</span>
            {polling && <span className="hint"> · 2초마다 새로 고칩니다 · 경과 {elapsedText(elapsed)}</span>}
          </p>
          <NextBanner job={job} onStage={setPicked} />
          {slow && (
            <div className="slow-note" role="status">
              <p>
                <strong>3분이 넘었습니다.</strong> 처리가 몰렸거나 시간을 넘겨 멈췄을 수 있습니다. 서류를 다시 올려 주세요.
              </p>
              <button type="button" className="link" onClick={() => navigate("/upload")}>
                파일 업로드로 가기
              </button>
            </div>
          )}
          {job.status === "failed" && (
            <p className="error" role="alert">
              {job.error ?? "작업이 실패했습니다"}
            </p>
          )}

          <StageBar job={job} active={active} onStage={setPicked} />
          <div className="stage-panel" role="tabpanel" id={`stage-panel-${active}`} aria-labelledby={`stage-tab-${active}`}>
            {active === "process" && (
              <div className="panel">
                <h2>처리 과정</h2>
                <StepList job={job} />
              </div>
            )}
            {active === "review" &&
              job.result &&
              (job.result.issues.length > 0 && viewFiles.length > 0 ? (
                <DocReview issues={job.result.issues} files={viewFiles} />
              ) : (
                <IssueList issues={job.result.issues} />
              ))}
            {active === "hs" && job.result && (
              <div id="job-hs">
                <HsPicker jobId={job.job_id} jobStatus={job.status} results={job.result.hs} />
              </div>
            )}
            {active === "declaration" && job.result && <DeclarationTable draft={job.result.declaration_draft} />}
            {active === "wms" && job.result && (
              <div id="job-wms">
                <WmsPanel
                  jobId={job.job_id}
                  jobStatus={job.status}
                  wms={job.result.wms}
                  // 불일치가 남으면 판독 오류 확인과 사유를 받아야 승인할 수 있다 (FB22, 판독 오류 예외)
                  blocked={nextActionOf(job).kind === "fix_docs" ? nextActionOf(job).message : null}
                />
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
