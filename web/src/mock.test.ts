// mock.ts: 가짜 서버가 약속 2의 모양으로 답하는지
import { describe, expect, it } from "vitest";
import jobExample from "../../docs/examples/job_waiting_approval.json";
import { ApiError } from "./api";
import { mockRequest } from "./mock";

describe("mockRequest", () => {
  it("POST /api/uploads 는 파일마다 uploads/ 로 시작하는 key 를 준다", async () => {
    const res = (await mockRequest("POST", "/api/uploads", {
      files: [
        { name: "a.pdf", content_type: "application/pdf" },
        { name: "b.png", content_type: "image/png" },
      ],
    })) as { uploads: { key: string; url: string }[] };

    expect(res.uploads).toHaveLength(2);
    expect(res.uploads.every((u) => u.key.startsWith("uploads/"))).toBe(true);
  });

  it("POST /api/jobs 는 예시의 job_id 를 준다", async () => {
    const res = await mockRequest("POST", "/api/jobs", { files: [] });
    expect(res).toEqual({ job_id: jobExample.job_id });
  });

  it("가짜 응답이 없는 경로는 404", async () => {
    await expect(mockRequest("GET", "/api/nothing", undefined)).rejects.toBeInstanceOf(ApiError);
  });
});
