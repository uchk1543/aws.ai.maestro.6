// mock.ts: 가짜 서버가 약속 2의 모양으로 답하는지
import { describe, expect, it } from "vitest";
import chatExample from "../../docs/examples/chat_response.json";
import jobExample from "../../docs/examples/job_waiting_approval.json";
import { ApiError } from "./api";
import { clearMockMismatches, mockJobAt, mockRequest, resetMock } from "./mock";
import type { Job } from "./types";

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

  it("POST /api/jobs/{id}/hs 는 고른 행을 사람 확정으로 바꾸고 신고서 초안을 준다", async () => {
    resetMock();
    const id = jobExample.job_id;
    const res = (await mockRequest("POST", `/api/jobs/${id}/hs`, { choices: [{ line: 1, hs: "8507600000" }] })) as {
      declaration_draft: unknown;
    };
    expect(res.declaration_draft).toEqual(jobExample.result.declaration_draft);

    // 진행 흉내(queued → running 단계들)를 지나면 최종 상태가 나온다
    let after: Job | undefined;
    for (let i = 0; i <= jobExample.steps.length + 1; i++) {
      after = (await mockRequest("GET", `/api/jobs/${id}`, undefined)) as Job;
    }
    expect(after!.result!.hs[0]).toMatchObject({ status: "사람 확정", by: "human", hs_code: "8507600000" });
    expect(after!.steps.at(-1)?.tool).toBe("confirm_by_human");
  });

  it("POST /api/jobs/{id}/hs 는 서버처럼 잘못된 요청을 400 으로 거절한다", async () => {
    resetMock();
    const id = jobExample.job_id;
    await expect(mockRequest("POST", `/api/jobs/${id}/hs`, { choices: [] })).rejects.toMatchObject({ status: 400 });
    await expect(mockRequest("POST", `/api/jobs/${id}/hs`, { choices: [{ line: 9, hs: "8507600000" }] })).rejects.toMatchObject({ status: 400 });
    await expect(mockRequest("POST", `/api/jobs/${id}/hs`, { choices: [{ line: 1, hs: "8507.60" }] })).rejects.toMatchObject({ status: 400 });
  });

  it("POST /api/jobs/{id}/approve 는 예시처럼 불일치가 남았으면 409", async () => {
    resetMock();
    await expect(
      mockRequest("POST", `/api/jobs/${jobExample.job_id}/approve`, { approver: "김담당" }),
    ).rejects.toMatchObject({ status: 409 });
  });

  it("POST /api/jobs/{id}/approve 는 불일치가 없으면 등록하고, approver 가 없으면 400", async () => {
    resetMock();
    clearMockMismatches();
    const id = jobExample.job_id;
    await expect(mockRequest("POST", `/api/jobs/${id}/approve`, { approver: " " })).rejects.toMatchObject({ status: 400 });

    const res = await mockRequest("POST", `/api/jobs/${id}/approve`, { approver: "김담당" });
    expect(res).toEqual({ wms: { status: "등록됨", wms_id: "WMS-MOCK-0001" } });
  });

  it("POST /api/chat 은 예시 답을 주고, session_id·message 가 없으면 400", async () => {
    const res = await mockRequest("POST", "/api/chat", { session_id: "s-1", message: "이번 주 통관 지연 건은?" });
    expect(res).toEqual(chatExample);
    await expect(mockRequest("POST", "/api/chat", { session_id: "s-1", message: " " })).rejects.toMatchObject({ status: 400 });
  });

  it("가짜 응답이 없는 경로는 404", async () => {
    await expect(mockRequest("GET", "/api/nothing", undefined)).rejects.toBeInstanceOf(ApiError);
  });
});
