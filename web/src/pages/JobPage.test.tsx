// G3 진행 화면: 2초 폴링 규칙과 steps 표시
import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import jobExample from "../../../docs/examples/job_waiting_approval.json";
import * as api from "../api";
import { renderWithQuery } from "../test-utils";
import type { Job } from "../types";
import { JobPage, POLL_MS, pollInterval } from "./JobPage";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, getJob: vi.fn() };
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
    expect(screen.getByText("승인 대기")).toBeInTheDocument();
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
});
