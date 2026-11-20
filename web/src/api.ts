// 화면이 부르는 /api 를 모은 곳 (docs/schema.md 약속 2).
// 주소는 항상 상대 경로다. 화면과 API 가 같은 CloudFront 주소라 CORS 가 필요 없다.
// npm run dev(모드 mock)에서는 mock.ts 가 docs/examples/ 로 대신 답한다. 빌드에는 들어가지 않는다.
import type {
  ApproveResponse,
  ChooseHsResponse,
  CreateJobResponse,
  HSChoice,
  Job,
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

/** 사람이 승인해 WMS 에 등록한다. 불일치가 남은 작업은 서버가 409 로 거절한다. */
export function approveJob(jobId: string, approver: string): Promise<ApproveResponse> {
  return request("POST", `/api/jobs/${encodeURIComponent(jobId)}/approve`, { approver });
}

/** 브라우저가 type 을 모르는 파일은 이 값으로 보낸다. */
export function contentTypeOf(file: File): string {
  return file.type || "application/octet-stream";
}
