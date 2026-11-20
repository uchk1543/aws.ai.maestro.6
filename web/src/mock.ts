// 가짜 서버 (npm run dev 전용). docs/examples/ 의 예시로 /api 에 답한다.
// 예시를 직접 읽으므로 예시가 바뀌면 가짜 응답도 같이 바뀐다.
import jobExample from "../../docs/examples/job_waiting_approval.json";
import { ApiError } from "./api";
import type { CreateJobResponse, Job, UploadRequestFile, UploadsResponse } from "./types";

const DELAY_MS = 300;
const example = jobExample as Job;

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// 작업마다 몇 번 조회됐는지. 진행 화면에서 단계가 하나씩 늘어나는 모습을 흉내 낸다.
const polls = new Map<string, number>();

/** n 번째 조회(0부터)의 작업 상태: queued → running(단계 하나씩) → 예시의 최종 상태 */
export function mockJobAt(jobId: string, n: number): Job {
  if (n === 0) return { job_id: jobId, status: "queued", steps: [], result: null, error: null };
  if (n <= example.steps.length) {
    return { job_id: jobId, status: "running", steps: example.steps.slice(0, n), result: null, error: null };
  }
  return { ...example, job_id: jobId };
}

/** api.ts 의 request 대신 불린다. 서버와 같은 경로·모양으로 답한다. */
export async function mockRequest(method: string, path: string, body: unknown): Promise<unknown> {
  await wait(DELAY_MS);
  if (method === "POST" && path === "/api/uploads") {
    const files = (body as { files: UploadRequestFile[] }).files;
    const res: UploadsResponse = {
      uploads: files.map((f, i) => ({ key: `uploads/mock/${i + 1}-${f.name}`, url: "mock://s3" })),
    };
    return res;
  }
  if (method === "POST" && path === "/api/jobs") {
    // 실제 서버는 새 job_id 를 만든다. 가짜는 예시의 job_id 를 돌려주고 진행을 처음부터 다시 흉내 낸다.
    polls.delete(example.job_id);
    const res: CreateJobResponse = { job_id: example.job_id };
    return res;
  }
  const job = path.match(/^\/api\/jobs\/([^/]+)$/);
  if (method === "GET" && job) {
    const jobId = decodeURIComponent(job[1]);
    if (jobId !== example.job_id) throw new ApiError(404, "작업을 찾을 수 없습니다");
    const n = polls.get(jobId) ?? 0;
    polls.set(jobId, n + 1);
    return mockJobAt(jobId, n);
  }
  throw new ApiError(404, `가짜 응답이 없는 경로입니다 (${method} ${path})`);
}
