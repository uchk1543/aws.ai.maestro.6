// G3 진행 화면: GET /api/jobs/{id} 를 2초마다 불러 단계 기록(steps)을 보여 준다
import { useQuery } from "@tanstack/react-query";
import { ApiError, getJob } from "../api";
import { DeclarationTable } from "../components/DeclarationTable";
import { HsPicker } from "../components/HsPicker";
import { IssueList } from "../components/IssueList";
import { WmsPanel } from "../components/WmsPanel";
import type { Job, JobStatus } from "../types";

export const POLL_MS = 2000;

const STATUS_KO: Record<JobStatus, string> = {
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

export function JobPage({ jobId }: { jobId: string }) {
  const query = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId),
    refetchInterval: (q) => pollInterval(q.state.data, q.state.error),
  });
  const job = query.data;
  const polling = pollInterval(job, query.error) !== false;

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
            {polling && <span className="hint"> · 2초마다 새로 고칩니다</span>}
          </p>
          {job.status === "failed" && (
            <p className="error" role="alert">
              {job.error ?? "작업이 실패했습니다"}
            </p>
          )}

          <div className="panel">
            <h2>진행 단계</h2>
            {job.steps.length === 0 ? (
              <p className="empty">아직 시작한 단계가 없습니다.</p>
            ) : (
              <ol className="steps" aria-label="진행 단계">
                {job.steps.map((s, i) => (
                  <li key={i} className={s.ok ? "step ok" : "step fail"}>
                    <span className="step-mark" aria-label={s.ok ? "성공" : "실패"}>
                      {s.ok ? "✔" : "✖"}
                    </span>
                    <span className="step-summary">{s.summary}</span>
                    <code className="step-tool">{s.tool}</code>
                  </li>
                ))}
              </ol>
            )}
          </div>

          {job.result && <IssueList issues={job.result.issues} />}
          {job.result && <HsPicker jobId={job.job_id} jobStatus={job.status} results={job.result.hs} />}
          {job.result && <DeclarationTable draft={job.result.declaration_draft} />}
          {job.result && <WmsPanel jobId={job.job_id} jobStatus={job.status} wms={job.result.wms} />}
        </>
      )}
    </section>
  );
}
