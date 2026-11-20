// mock.ts: 가짜 서버가 약속 2의 모양으로 답하는지
import { describe, expect, it } from "vitest";
import jobExample from "../../docs/examples/job_waiting_approval.json";
import { ApiError } from "./api";
import { mockJobAt, mockRequest } from "./mock";

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

  it("작업 조회는 queued → running(단계 하나씩) → 예시의 최종 상태로 바뀐다", () => {
    const n = jobExample.steps.length;
    expect(mockJobAt("job-7c1e", 0).status).toBe("queued");
    expect(mockJobAt("job-7c1e", 1)).toMatchObject({ status: "running", steps: jobExample.steps.slice(0, 1) });
    expect(mockJobAt("job-7c1e", n).steps).toHaveLength(n);
    expect(mockJobAt("job-7c1e", n + 1)).toEqual(jobExample);
  });

  it("GET /api/jobs/{id} 는 조회할 때마다 한 단계씩 진행하고, 없는 작업은 404", async () => {
    await mockRequest("POST", "/api/jobs", { files: [] });
    const first = (await mockRequest("GET", `/api/jobs/${jobExample.job_id}`, undefined)) as { status: string };
    const second = (await mockRequest("GET", `/api/jobs/${jobExample.job_id}`, undefined)) as { status: string };

    expect(first.status).toBe("queued");
    expect(second.status).toBe("running");
    await expect(mockRequest("GET", "/api/jobs/job-ffffffff", undefined)).rejects.toMatchObject({ status: 404 });
  });

  it("가짜 응답이 없는 경로는 404", async () => {
    await expect(mockRequest("GET", "/api/nothing", undefined)).rejects.toBeInstanceOf(ApiError);
  });
});
