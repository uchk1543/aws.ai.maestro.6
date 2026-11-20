// 가짜 서버 (npm run dev 전용). docs/examples/ 의 예시로 /api 에 답한다.
// 예시를 직접 읽으므로 예시가 바뀌면 가짜 응답도 같이 바뀐다.
// 판정·신고서 채우기는 흉내 내지 않는다. 사람이 고른 값을 상태에 반영하는 것만 한다.
import chatExample from "../../docs/examples/chat_response.json";
import jobExample from "../../docs/examples/job_waiting_approval.json";
// 임시(제안 중): 서버 약속이 합쳐지면 docs/examples/documents.json 으로 바꾼다
import documentsDraft from "./fixtures/documents.draft.json";
// 임시(제안 중): F11(#195)이 합쳐지면 docs/examples/stats.json 으로 바꾼다
import statsDraft from "./fixtures/stats.draft.json";
// 임시: #252 PR A(작업 목록 API)가 합쳐지면 docs/examples/jobs.json 으로 바꾼다
import jobsDraft from "./fixtures/jobs.draft.json";
import { ApiError } from "./api";
import { fileViewOf } from "./mockDocs";
import { nextActionOf } from "./nextAction";
import type {
  ApproveResponse,
  ChatHistoryLine,
  ChatRequest,
  ChatResponse,
  ChooseHsResponse,
  CreateJobResponse,
  DocType,
  DocumentRecord,
  DocumentsResponse,
  HSChoice,
  Job,
  JobFilesResponse,
  JobListResponse,
  StatsResponse,
  UploadRequestFile,
  UploadsResponse,
} from "./types";

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

/** POST /api/jobs/{id}/approve: 약속 2대로 불일치가 남았으면 409, 아니면 사람 승인으로 등록. */
function approve(body: unknown): ApproveResponse {
  const approver = (body as { approver?: unknown } | undefined)?.approver;
  if (typeof approver !== "string" || approver.trim() === "") throw new ApiError(400, "approver가 필요합니다");
  const result = finalJob.result;
  if (finalJob.status !== "waiting_approval" || !result) {
    throw new ApiError(409, `승인 대기 중인 작업이 아닙니다 (지금: ${finalJob.status})`);
  }
  if (result.issues.some((i) => i.grade === "불일치")) {
    throw new ApiError(409, "불일치가 남아 있어 WMS에 등록할 수 없습니다");
  }
  result.wms = {
    status: "등록됨",
    by: "human",
    wms_id: "WMS-MOCK-0001",
    approver,
    approved_at: new Date().toISOString().slice(0, 19) + "+09:00",
  };
  finalJob.steps.push({ tool: "push_to_wms", summary: `사람 승인(${approver})으로 WMS 등록`, ok: true });
  return { wms: { status: "등록됨", wms_id: "WMS-MOCK-0001" } };
}

/** 가짜 작업의 불일치를 없앤다. 예시에는 불일치가 있어서, 테스트에서 승인 성공 경로를 볼 때 쓴다. */
export function clearMockMismatches(): void {
  if (finalJob.result) finalJob.result.issues = finalJob.result.issues.filter((i) => i.grade !== "불일치");
}

const DOCS_PAGE = 3;
const DOC_TYPE_SET = new Set<string>(["commercial_invoice", "packing_list", "bill_of_lading", "certificate_of_origin", "unknown"]);

/** GET /api/documents: 임시 가짜 데이터에서 그 종류만 골라 한 쪽(3건)씩 준다. counts 는 파일에 적힌 값 그대로. */
// 가짜 작업마다 거르기에 쓰는 사실 (F11 거르기 흉내). 예시 작업(job-7c1e)은 불일치 X-WT-01 과 HS 고를 품목이 있다
const JOB_FACTS: Record<string, { grades: string[]; rules: string[]; hsPending: boolean }> = {
  "job-7c1e": { grades: ["불일치"], rules: ["X-WT-01"], hsPending: true },
};

function jobMatches(record: DocumentRecord, query: URLSearchParams): boolean {
  const facts = JOB_FACTS[record.job_id] ?? { grades: [], rules: [], hsPending: false };
  const status = query.get("job_status");
  const grade = query.get("grade");
  const rule = query.get("rule_id");
  if (status && record.job_status !== status) return false;
  if (grade && !facts.grades.includes(grade)) return false;
  if (rule && !facts.rules.includes(rule)) return false;
  if (query.get("hs") === "pending" && !facts.hsPending) return false;
  return true;
}

function documents(query: URLSearchParams): DocumentsResponse {
  const docType = query.get("doc_type") ?? "";
  if (!DOC_TYPE_SET.has(docType)) throw new ApiError(400, "doc_type은 commercial_invoice, packing_list, bill_of_lading, certificate_of_origin, unknown 중 하나입니다");
  const draft = documentsDraft as { counts: Record<DocType, number>; items: DocumentRecord[] };
  const filtered = ["job_status", "grade", "rule_id", "hs"].some((k) => query.get(k));
  const kept = filtered ? draft.items.filter((d) => jobMatches(d, query)) : draft.items;
  // 거르기가 있으면 counts 도 그 안에서 센다 (없으면 파일에 적힌 값 그대로)
  const counts = filtered
    ? (Object.fromEntries([...DOC_TYPE_SET].map((t) => [t, kept.filter((d) => d.doc_type === t).length])) as Record<DocType, number>)
    : copy(draft.counts);
  const all = kept.filter((d) => d.doc_type === docType);
  const start = Number(query.get("cursor") ?? "0") || 0;
  const end = start + DOCS_PAGE;
  return { counts, items: copy(all.slice(start, end)), next_cursor: end < all.length ? String(end) : null };
}

/** GET /api/jobs/{id}/files: 임시 가짜 데이터에서 그 작업의 서류마다 가짜 쪽 그림과 표시를 만든다 (G11). */
function jobFiles(jobId: string): JobFilesResponse {
  const records = (documentsDraft as { items: DocumentRecord[] }).items.filter((d) => d.job_id === jobId);
  if (records.length === 0) throw new ApiError(404, "작업을 찾을 수 없습니다");
  return { files: records.map(fileViewOf) };
}

// 대화 기록 (E6 #157 흉내): 새로 고쳐도 남도록 브라우저 localStorage 에 둔다. 개발용 가짜 서버만 쓴다
const CHAT_STORE = "team06-mock-chat";

function chatStore(): Record<string, ChatHistoryLine[]> {
  try {
    return JSON.parse(localStorage.getItem(CHAT_STORE) ?? "{}");
  } catch {
    return {};
  }
}

function chatLines(sessionId: string): ChatHistoryLine[] {
  return (chatStore()[sessionId] ?? []).slice(-50);
}

function saveChatLines(sessionId: string, question: string, res: ChatResponse): void {
  const store = chatStore();
  const ts = `${Date.now()}#mock`;
  const blocked = res.blocked ?? null;
  store[sessionId] = [
    ...(store[sessionId] ?? []),
    { session_id: sessionId, ts: `${ts}#0`, role: "user", text: question, filters: null, count: null, rule: null, blocked: null, block_reason: null },
    {
      session_id: sessionId,
      ts: `${ts}#1`,
      role: "assistant",
      text: res.answer,
      filters: blocked ? null : res.filters,
      count: blocked ? null : res.rows.length,
      rule: null,
      blocked: blocked !== null,
      block_reason: blocked,
    },
  ];
  try {
    localStorage.setItem(CHAT_STORE, JSON.stringify(store));
  } catch {
    // 저장 못 해도 가짜 응답은 계속 준다
  }
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
  if (method === "POST" && path === "/api/chat") {
    const req = body as Partial<ChatRequest> | undefined;
    if (!req?.session_id || !req.message?.trim()) throw new ApiError(400, "session_id와 message가 필요합니다");
    // 가짜는 질문과 상관없이 예시 답을 준다. 서버처럼 질문·답 두 줄을 기록에 남긴다 (E6)
    const res = copy(chatExample as ChatResponse);
    saveChatLines(req.session_id, req.message.trim(), res);
    return res;
  }
  const chatRoute = path.match(/^\/api\/chat\/([^/]+)$/);
  if (method === "GET" && chatRoute) return { messages: chatLines(decodeURIComponent(chatRoute[1])) };
  const [pathname, search = ""] = path.split("?");
  if (method === "GET" && pathname === "/api/documents") return documents(new URLSearchParams(search));
  if (method === "GET" && pathname === "/api/jobs") {
    const kind = new URLSearchParams(search).get("next_action");
    const items = (jobsDraft as unknown as JobListResponse).items.filter((j) => !kind || j.next_action.kind === kind);
    return copy({ items });
  }
  if (method === "GET" && pathname === "/api/stats") {
    const { _note, ...stats } = statsDraft as StatsResponse & { _note?: string };
    void _note;
    return copy(stats);
  }
  const route = path.match(/^\/api\/jobs\/([^/]+)(?:\/([a-z]+))?$/);
  if (route) {
    const jobId = decodeURIComponent(route[1]);
    if (method === "GET" && route[2] === "files") return jobFiles(jobId);
    if (jobId !== example.job_id) throw new ApiError(404, "작업을 찾을 수 없습니다");
    if (method === "GET" && !route[2]) {
      const n = polls.get(jobId) ?? 0;
      polls.set(jobId, n + 1);
      // 서버처럼 응답 때마다 다음 할 일을 정한다 (FB22). 예시에 적힌 값은 처리 전 단계와 맞지 않으므로 다시 정한다
      const job = mockJobAt(jobId, n, finalJob);
      return { ...job, next_action: nextActionOf({ ...job, next_action: null }) };
    }
    if (method === "POST" && route[2] === "hs") return chooseHs(body);
    if (method === "POST" && route[2] === "approve") return approve(body);
  }
  throw new ApiError(404, `가짜 응답이 없는 경로입니다 (${method} ${path})`);
}
