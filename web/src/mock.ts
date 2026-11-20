// 가짜 서버 (npm run dev 전용). docs/examples/ 의 예시로 /api 에 답한다.
// 예시를 직접 읽으므로 예시가 바뀌면 가짜 응답도 같이 바뀐다.
// 판정·신고서 채우기는 흉내 내지 않는다. 사람이 고른 값을 상태에 반영하는 것만 한다.
import jobExample from "../../docs/examples/job_waiting_approval.json";
import { ApiError } from "./api";
import type { ChooseHsResponse, CreateJobResponse, HSChoice, Job, UploadRequestFile, UploadsResponse } from "./types";

const DELAY_MS = 300;
const example = jobExample as Job;
const HS_CODE = /^[0-9]{10}$/;

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function copy<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

// 작업마다 몇 번 조회됐는지. 진행 화면에서 단계가 하나씩 늘어나는 모습을 흉내 낸다.
const polls = new Map<string, number>();
// 처리가 끝난 뒤의 작업 상태. 사람이 HS 를 고르면 여기에 반영한다.
let finalJob: Job = copy(example);

/** 가짜 작업을 처음 상태로 되돌린다 (새 업로드, 테스트). */
export function resetMock(): void {
  polls.clear();
  finalJob = copy(example);
}

/** n 번째 조회(0부터)의 작업 상태: queued → running(단계 하나씩) → 최종 상태 */
export function mockJobAt(jobId: string, n: number, last: Job = example): Job {
  if (n === 0) return { job_id: jobId, status: "queued", steps: [], result: null, error: null };
  if (n <= example.steps.length) {
    return { job_id: jobId, status: "running", steps: example.steps.slice(0, n), result: null, error: null };
  }
  return { ...copy(last), job_id: jobId };
}

/** POST /api/jobs/{id}/hs: 서버(api/handler.py choose_hs)와 같은 검사 후 사람 확정으로 바꾼다. */
function chooseHs(body: unknown): ChooseHsResponse {
  if (finalJob.status !== "waiting_approval" || !finalJob.result) {
    throw new ApiError(409, `HS는 승인 대기 중인 작업에서만 고를 수 있습니다 (지금: ${finalJob.status})`);
  }
  const result = finalJob.result;
  const choices = (body as { choices?: HSChoice[] } | undefined)?.choices;
  if (!Array.isArray(choices) || choices.length === 0) throw new ApiError(400, "choices 목록이 비어 있습니다");
  const lines = result.hs.map((h) => h.line);
  for (const c of choices) {
    if (!lines.includes(c.line)) throw new ApiError(400, `line은 이 작업의 품목 행 [${lines.join(", ")}] 중 하나입니다`);
    if (!HS_CODE.test(c.hs)) throw new ApiError(400, "hs는 숫자 10자리입니다 (예: 8507600000)");
  }
  result.hs = result.hs.map((h) => {
    const c = choices.find((x) => x.line === h.line);
    return c ? { ...h, status: "사람 확정", by: "human", hs_code: c.hs } : h;
  });
  const chosen = choices.map((c) => `${c.line}행 ${c.hs}`).join(", ");
  finalJob.steps.push({ tool: "confirm_by_human", summary: `사람 확정: ${chosen}`, ok: true });
  return { declaration_draft: copy(result.declaration_draft!) };
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
    resetMock();
    const res: CreateJobResponse = { job_id: example.job_id };
    return res;
  }
  const route = path.match(/^\/api\/jobs\/([^/]+)(?:\/([a-z]+))?$/);
  if (route) {
    const jobId = decodeURIComponent(route[1]);
    if (jobId !== example.job_id) throw new ApiError(404, "작업을 찾을 수 없습니다");
    if (method === "GET" && !route[2]) {
      const n = polls.get(jobId) ?? 0;
      polls.set(jobId, n + 1);
      return mockJobAt(jobId, n, finalJob);
    }
    if (method === "POST" && route[2] === "hs") return chooseHs(body);
  }
  throw new ApiError(404, `가짜 응답이 없는 경로입니다 (${method} ${path})`);
}
