// 화면이 부르는 /api 를 모은 곳 (docs/schema.md 약속 2).
// 주소는 항상 상대 경로다. 화면과 API 가 같은 CloudFront 주소라 CORS 가 필요 없다.
// npm run dev(모드 mock)에서는 mock.ts 가 docs/examples/ 로 대신 답한다. 빌드에는 들어가지 않는다.
import type {
  ApproveResponse,
  ChatHistoryResponse,
  ChatRequest,
  ChatResponse,
  ChooseHsResponse,
  CreateJobResponse,
  DocType,
  DocumentFilters,
  DocumentsResponse,
  HSChoice,
  Job,
  JobFilesResponse,
  JobListResponse,
  StatsResponse,
  TodoKind,
  JobFile,
  UploadRequestFile,
  UploadsResponse,
} from "./types";

/** 서버가 2xx 가 아닌 응답을 줬을 때. message 는 서버의 {"error"} 문장이다. */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (import.meta.env.MODE === "mock") {
    const { mockRequest } = await import("./mock");
    return mockRequest(method, path, body) as Promise<T>;
  }
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const message = data && typeof data.error === "string" ? data.error : `요청 실패 (${res.status})`;
    throw new ApiError(res.status, message);
  }
  return data as T;
}

/** 파일마다 S3 업로드 주소를 받는다. */
export function createUploads(files: UploadRequestFile[]): Promise<UploadsResponse> {
  return request("POST", "/api/uploads", { files });
}

/** 받은 주소로 파일을 S3 에 직접 올린다. content-type 은 createUploads 에 보낸 값과 같아야 한다. */
export async function putToS3(url: string, file: Blob, contentType: string): Promise<void> {
  if (import.meta.env.MODE === "mock") return;
  const res = await fetch(url, { method: "PUT", headers: { "content-type": contentType }, body: file });
  if (!res.ok) throw new ApiError(res.status, `S3 업로드 실패 (${res.status})`);
}

/** 올린 파일로 작업을 만든다. job_id 를 바로 돌려받는다. */
export function createJob(files: JobFile[]): Promise<CreateJobResponse> {
  return request("POST", "/api/jobs", { files });
}

/** 작업 상태를 받는다. 진행 화면이 2초마다 부른다. */
export function getJob(jobId: string): Promise<Job> {
  return request("GET", `/api/jobs/${encodeURIComponent(jobId)}`);
}

/** '사람 확인 필요' 품목에서 사람이 고른 HS 를 보낸다. 서버가 확정하고 신고서 초안을 다시 채운다. */
export function chooseHs(jobId: string, choices: HSChoice[]): Promise<ChooseHsResponse> {
  return request("POST", `/api/jobs/${encodeURIComponent(jobId)}/hs`, { choices });
}

/** 사람이 승인해 WMS 에 등록한다. 불일치가 남은 작업은 판독 오류 사유(overrideReason)가 없으면 서버가 409 로 거절한다. */
export function approveJob(jobId: string, approver: string, overrideReason?: string): Promise<ApproveResponse> {
  const body = overrideReason ? { approver, override_reason: overrideReason } : { approver };
  return request("POST", `/api/jobs/${encodeURIComponent(jobId)}/approve`, body);
}
/** HS 확인 요청서 PDF 내려받기 주소 (GET /api/jobs/{id}/hs-request, X2 #260). HS가 '사람 확인 필요'로 남은 품목이 있을 때 받는다 */
export function hsRequestUrl(jobId: string): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/hs-request`;
}
/** 검수 완료서 PDF 내려받기 주소 (GET /api/jobs/{id}/certificate, X1 #258). 사람이 승인해 등록한 작업만 받을 수 있다 */
export function certificateUrl(jobId: string): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/certificate`;
}

/** 현황 채팅에 질문을 보낸다. 서버는 앞 질문을 기억하지 않고 질문마다 따로 답한다 (session_id 는 기록용, FB09 #166). */
export function sendChat(req: ChatRequest): Promise<ChatResponse> {
  return request("POST", "/api/chat", req);
}

/** 문서 분류 내역: 한 종류의 서류 목록과 종류별 건수 (G10, docs/schema.md GET /api/documents #143). cursor 는 앞 응답의 next_cursor. */
export function getDocuments(
  docType: DocType,
  cursor: string | null = null,
  filters: DocumentFilters = {},
): Promise<DocumentsResponse> {
  const query = new URLSearchParams({ doc_type: docType });
  if (cursor) query.set("cursor", cursor);
  // 거르기 (F11 #195): 대시보드 통계에서 들어올 때
  for (const [k, v] of Object.entries(filters)) if (v) query.set(k, v);
  return request("GET", `/api/documents?${query.toString()}`);
}

/** 대시보드 통계 (F11 #195). 숫자는 서버가 센다. */
export function getStats(): Promise<StatsResponse> {
  return request("GET", "/api/stats");
}

/** 다음 할 일이 같은 작업 목록 (#252). 대시보드 카드를 누르면 그 자리에 펼친다. 개수는 통계의 같은 칸과 같다. */
export function getJobs(kind: TodoKind): Promise<JobListResponse> {
  return request("GET", `/api/jobs?${new URLSearchParams({ next_action: kind }).toString()}`);
}

/** 서류 보기: 작업에 올라온 서류의 원본 주소·쪽 그림·칸 위치·읽은 칸 (G11, docs/schema.md GET /api/jobs/{id}/files #156·#189). */
export function getJobFiles(jobId: string): Promise<JobFilesResponse> {
  return request("GET", `/api/jobs/${encodeURIComponent(jobId)}/files`);
}

/** 브라우저가 type 을 모르는 파일은 이 값으로 보낸다. */
export function contentTypeOf(file: File): string {
  return file.type || "application/octet-stream";
}

/** 현황 채팅 기록 (E6 #157): 그 세션의 최근 질문·답 줄, 오래된 순. 화면을 열 때 불러와 새로 고쳐도 대화가 남게 한다 (G14). */
export function getChatHistory(sessionId: string): Promise<ChatHistoryResponse> {
  return request("GET", `/api/chat/${encodeURIComponent(sessionId)}`);
}
