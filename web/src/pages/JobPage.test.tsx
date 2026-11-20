// G3 진행 화면: 2초 폴링 규칙과 steps 표시
import { act, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import jobExample from "../../../docs/examples/job_waiting_approval.json";
import * as api from "../api";
import { renderWithQuery } from "../test-utils";
import type { Job } from "../types";
import { fileViewOf } from "../mockDocs";
import draft from "../fixtures/documents.draft.json";
import type { DocumentRecord } from "../types";
import { elapsedText, JobPage, POLL_MS, pollInterval, SLOW_MS } from "./JobPage";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, getJob: vi.fn(), getJobFiles: vi.fn() };
});

const example = jobExample as Job;
const at = (status: Job["status"], extra: Partial<Job> = {}): Job => ({
  job_id: "job-0000abcd",
  status,
  steps: [],
  result: null,
  ...extra,
});

beforeEach(() => {
  vi.mocked(api.getJob).mockReset();
  // 지금 서버에는 서류 보기 경로가 없다 (G11 제안 중) → 글자 오류 목록으로 보여 준다
  vi.mocked(api.getJobFiles).mockReset().mockRejectedValue(new api.ApiError(404, "없는 경로입니다"));
});

describe("pollInterval", () => {
  it("queued·running 이면 2초마다", () => {
    expect(POLL_MS).toBe(2000);
    expect(pollInterval(at("queued"), null)).toBe(2000);
    expect(pollInterval(at("running"), null)).toBe(2000);
    expect(pollInterval(undefined, null)).toBe(2000);
  });

  it("승인 대기·끝남·실패면 멈춘다", () => {
    expect(pollInterval(at("waiting_approval"), null)).toBe(false);
    expect(pollInterval(at("done"), null)).toBe(false);
    expect(pollInterval(at("failed"), null)).toBe(false);
  });

  it("없는 작업(404)이면 멈춘다", () => {
    expect(pollInterval(undefined, new api.ApiError(404, "작업을 찾을 수 없습니다"))).toBe(false);
  });
});

describe("JobPage", () => {
  it("steps 를 순서대로 보여 준다", async () => {
    vi.mocked(api.getJob).mockResolvedValue(example);
    renderWithQuery(<JobPage jobId="job-7c1e" />);

    expect(await screen.findByText("bl.jpg → 선하증권")).toBeInTheDocument();
    const items = within(screen.getByRole("list", { name: "진행 단계" })).getAllByRole("listitem");
    expect(items).toHaveLength(example.steps.length);
    expect(items[2]).toHaveTextContent("불일치 1건");
    expect(items[2]).toHaveTextContent("cross_check");
    expect(screen.getByText("승인 대기", { selector: ".status" })).toBeInTheDocument();
    expect(api.getJob).toHaveBeenCalledWith("job-7c1e");
  });

  it("결과가 있으면 오류 목록을 보여 주고, 결과 전에는 보이지 않는다", async () => {
    vi.mocked(api.getJob).mockResolvedValue(example);
    const { unmount } = renderWithQuery(<JobPage jobId="job-7c1e" />);
    expect(await screen.findByText("오류 목록 (1)")).toBeInTheDocument();
    unmount();

    vi.mocked(api.getJob).mockResolvedValue(at("running", { steps: [example.steps[0]] }));
    renderWithQuery(<JobPage jobId="job-0000abcd" />);
    expect(await screen.findByText("처리 중")).toBeInTheDocument();
    expect(screen.queryByText("오류 목록", { exact: false })).not.toBeInTheDocument();
  });

  it("처리 중이면 새로 고친다는 안내가 보인다", async () => {
    vi.mocked(api.getJob).mockResolvedValue(at("running", { steps: [example.steps[0]] }));
    renderWithQuery(<JobPage jobId="job-0000abcd" />);

    expect(await screen.findByText("처리 중")).toBeInTheDocument();
    expect(screen.getByText("· 2초마다 새로 고칩니다", { exact: false })).toBeInTheDocument();
  });

  it("실패한 단계와 실패 이유를 보여 준다", async () => {
    vi.mocked(api.getJob).mockResolvedValue(
      at("failed", { steps: [{ tool: "read_document", summary: "invoice.pdf 읽기 실패", ok: false }], error: "ReadError: 파일이 너무 큽니다" }),
    );
    renderWithQuery(<JobPage jobId="job-0000abcd" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("ReadError: 파일이 너무 큽니다");
    expect(screen.getByLabelText("실패")).toBeInTheDocument();
  });

  it("없는 작업이면 서버 오류 문장을 보여 준다", async () => {
    vi.mocked(api.getJob).mockRejectedValue(new api.ApiError(404, "작업을 찾을 수 없습니다"));
    renderWithQuery(<JobPage jobId="job-ffffffff" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("작업을 찾을 수 없습니다");
  });
  it("서버가 서류 그림을 주면 서류 | 오류 보기를, 못 주면 글자 오류 목록을 보여 준다", async () => {
    vi.mocked(api.getJob).mockResolvedValue(example);
    const records = (draft.items as DocumentRecord[]).filter((d) => d.job_id === "job-7c1e");
    vi.mocked(api.getJobFiles).mockResolvedValue({ files: records.map(fileViewOf) });
    const { unmount } = renderWithQuery(<JobPage jobId="job-7c1e" />);

    expect(await screen.findByRole("tablist", { name: "서류" })).toBeInTheDocument();
    expect(screen.getByText("오류 목록 (1)")).toBeInTheDocument();
    expect(api.getJobFiles).toHaveBeenCalledWith("job-7c1e");
    unmount();

    vi.mocked(api.getJobFiles).mockRejectedValue(new api.ApiError(404, "없는 경로입니다"));
    renderWithQuery(<JobPage jobId="job-7c1e" />);
    expect(await screen.findByText("오류 목록 (1)")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("처리 중이 3분을 넘으면 경과 시간과 다시 올리라는 안내가 나온다 (FB20)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.mocked(api.getJob).mockResolvedValue(at("running", { steps: [example.steps[0]] }));
      renderWithQuery(<JobPage jobId="job-0000abcd" />);
      expect(await screen.findByText(/경과 0초/)).toBeInTheDocument();
      expect(screen.queryByText(/3분이 넘었습니다/)).not.toBeInTheDocument();

      await act(async () => {
        vi.advanceTimersByTime(SLOW_MS - 2000);
      });
      expect(screen.getByText(/경과 2분 58초/)).toBeInTheDocument();
      expect(screen.queryByText(/3분이 넘었습니다/)).not.toBeInTheDocument();

      await act(async () => {
        vi.advanceTimersByTime(3000);
      });
      expect(screen.getByRole("status")).toHaveTextContent("3분이 넘었습니다");
      expect(screen.getByRole("button", { name: "파일 업로드로 가기" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("끝난 작업에는 경과 시간과 안내를 보이지 않는다", async () => {
    vi.mocked(api.getJob).mockResolvedValue({ ...example, status: "done" });
    renderWithQuery(<JobPage jobId="job-0000abcd" />);
    expect(await screen.findByText("끝남")).toBeInTheDocument();
    expect(screen.queryByText(/경과/)).not.toBeInTheDocument();
  });

  it("elapsedText 는 분·초로 적는다", () => {
    expect([0, 59_999, 72_000, 180_000].map(elapsedText)).toEqual(["0초", "59초", "1분 12초", "3분 0초"]);
  });
});
