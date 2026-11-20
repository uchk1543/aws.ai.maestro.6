// 가짜 서버 (npm run dev 전용). docs/examples/ 의 예시로 /api 에 답한다.
// 예시를 직접 읽으므로 예시가 바뀌면 가짜 응답도 같이 바뀐다.
import jobExample from "../../docs/examples/job_waiting_approval.json";
import { ApiError } from "./api";
import type { CreateJobResponse, UploadRequestFile, UploadsResponse } from "./types";

const DELAY_MS = 300;

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
    // 실제 서버는 새 job_id 를 만든다. 가짜는 예시의 job_id 를 돌려준다.
    const res: CreateJobResponse = { job_id: jobExample.job_id };
    return res;
  }
  throw new ApiError(404, `가짜 응답이 없는 경로입니다 (${method} ${path})`);
}
