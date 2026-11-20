// api.ts: 서버를 부르지 않고 fetch 를 가짜로 바꿔 경로·본문·오류 처리를 본다
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, approveJob, chooseHs, contentTypeOf, createJob, createUploads, putToS3, sendChat } from "./api";

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api", () => {
  it("POST /api/uploads 에 파일 이름과 content_type 을 보낸다", async () => {
    const fetchMock = vi.fn(() => reply(200, { uploads: [{ key: "uploads/a/inv.pdf", url: "https://s3/put" }] }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await createUploads([{ name: "inv.pdf", content_type: "application/pdf" }]);

    expect(res.uploads[0].key).toBe("uploads/a/inv.pdf");
    const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe("/api/uploads");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ files: [{ name: "inv.pdf", content_type: "application/pdf" }] });
  });

  it("POST /api/jobs 에 key 와 doc_type(null 포함)을 보낸다", async () => {
    const fetchMock = vi.fn(() => reply(200, { job_id: "job-0000abcd" }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await createJob([
      { key: "uploads/a/inv.pdf", doc_type: "commercial_invoice" },
      { key: "uploads/a/pl.pdf", doc_type: null },
    ]);

    expect(res.job_id).toBe("job-0000abcd");
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string).files[1]).toEqual({ key: "uploads/a/pl.pdf", doc_type: null });
  });

  it("서버 오류는 {error} 문장을 담은 ApiError 가 된다", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply(400, { error: "files 목록이 비어 있습니다" })));

    const err = await createJob([]).catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(400);
    expect(err.message).toBe("files 목록이 비어 있습니다");
  });

  it("S3 PUT 은 받은 url 로 content-type 하나만 붙여 보낸다", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    const file = new Blob(["%PDF"], { type: "application/pdf" });

    await putToS3("https://s3/put?sig=1", file, "application/pdf");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://s3/put?sig=1");
    expect(init.method).toBe("PUT");
    expect(init.headers).toEqual({ "content-type": "application/pdf" });
  });

  it("POST /api/jobs/{id}/hs 에 choices 를 보낸다", async () => {
    const fetchMock = vi.fn(() => reply(200, { declaration_draft: { fields: [], blank_fields: [], pdf_url: null } }));
    vi.stubGlobal("fetch", fetchMock);

    await chooseHs("job-0000abcd", [{ line: 1, hs: "8507600000" }]);

    const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe("/api/jobs/job-0000abcd/hs");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ choices: [{ line: 1, hs: "8507600000" }] });
  });

  it("POST /api/jobs/{id}/approve 에 approver 를 보내고, 409 는 ApiError(409)", async () => {
    const fetchMock = vi.fn(() => reply(409, { error: "불일치가 남아 있습니다" }));
    vi.stubGlobal("fetch", fetchMock);

    const err = await approveJob("job-0000abcd", "김담당").catch((e) => e);

    const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe("/api/jobs/job-0000abcd/approve");
    expect(JSON.parse(init.body as string)).toEqual({ approver: "김담당" });
    expect(err).toMatchObject({ status: 409, message: "불일치가 남아 있습니다" });
  });

  it("POST /api/chat 에 session_id 와 message 를 보낸다", async () => {
    const fetchMock = vi.fn(() => reply(200, { answer: "0건입니다.", filters: {}, period_resolved: null, rows: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await sendChat({ session_id: "s-1", message: "이번 주 통관 지연 건은?" });

    const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe("/api/chat");
    expect(JSON.parse(init.body as string)).toEqual({ session_id: "s-1", message: "이번 주 통관 지연 건은?" });
  });

  it("S3 PUT 이 실패하면 ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(null, { status: 403 }))));

    await expect(putToS3("https://s3/put", new Blob(["x"]), "image/png")).rejects.toThrow("S3 업로드 실패 (403)");
  });

  it("type 을 모르는 파일은 application/octet-stream", () => {
    expect(contentTypeOf(new File(["x"], "scan"))).toBe("application/octet-stream");
    expect(contentTypeOf(new File(["x"], "a.png", { type: "image/png" }))).toBe("image/png");
  });
});
