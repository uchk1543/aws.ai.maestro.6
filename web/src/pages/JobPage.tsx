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
import { navigate } from "../route";
import type { Job, JobStatus } from "../types";

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

          {job.result &&
            (job.result.issues.length > 0 && viewFiles.length > 0 ? (
              <DocReview issues={job.result.issues} files={viewFiles} />
            ) : (
              <IssueList issues={job.result.issues} />
            ))}
          {job.result && <HsPicker jobId={job.job_id} jobStatus={job.status} results={job.result.hs} />}
          {job.result && <DeclarationTable draft={job.result.declaration_draft} />}
          {job.result && <WmsPanel jobId={job.job_id} jobStatus={job.status} wms={job.result.wms} />}
        </>
      )}
    </section>
  );
}
