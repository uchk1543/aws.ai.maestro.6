// G3 진행 화면: 2초 폴링 규칙과 steps 표시
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import jobExample from "../../../docs/examples/job_waiting_approval.json";
import * as api from "../api";
import { renderWithQuery } from "../test-utils";
import type { Job } from "../types";
import { fileViewOf } from "../mockDocs";
import draft from "../fixtures/documents.draft.json";
import type { DocumentRecord } from "../types";
import { defaultStage, elapsedText, groupSteps, JobPage, POLL_MS, pollInterval, SLOW_MS, stageInfo } from "./JobPage";

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

    await userEvent.setup().click(await screen.findByRole("tab", { name: /처리 과정/ }));
    expect(await screen.findByText("bl.jpg → 선하증권")).toBeInTheDocument();
    const items = within(screen.getByRole("tabpanel")).getAllByRole("listitem");
    expect(items).toHaveLength(example.steps.length);
    const cross = items.find((li) => li.textContent?.includes("cross_check"))!;
    expect(cross).toHaveTextContent("불일치 1건");
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
    expect(within(screen.getByRole("tabpanel")).getByLabelText("실패")).toBeInTheDocument();
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
    expect(screen.queryByRole("tablist", { name: "서류" })).not.toBeInTheDocument();
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

  it("맨 위에 다음 할 일 한 줄을 보인다: 불일치 · HS · 확인만 남음 (FB22)", async () => {
    const base = example.result!;
    const cases: [Job, string, string][] = [
      [{ ...example, next_action: undefined }, "불일치 1건: 서류를 고쳐 다시 올리거나, 원본을 확인해 판독 오류면 사유를 적고 승인하세요", "파일 업로드로"],
      [
        { ...example, next_action: undefined, result: { ...base, issues: base.issues.map((i) => ({ ...i, grade: "확인 필요" as const })) } },
        "HS 1개를 고르세요",
        "HS 고르기로",
      ],
      [
        {
          ...example,
          next_action: undefined,
          result: { ...base, issues: base.issues.map((i) => ({ ...i, grade: "확인 필요" as const })), hs: base.hs.map((h) => ({ ...h, status: "사람 확정" as const, by: "human" as const, hs_code: "8507609000" })) },
        },
        "확인 필요 1건을 확인한 뒤 승인하세요",
        "승인 칸으로",
      ],
    ];
    for (const [job, message, button] of cases) {
      vi.mocked(api.getJob).mockResolvedValue(job);
      const { unmount } = renderWithQuery(<JobPage jobId="job-0000abcd" />);
      const banner = await screen.findByRole("region", { name: "다음 할 일" });
      expect(banner).toHaveTextContent(message);
      expect(within(banner).getByRole("button", { name: button })).toBeInTheDocument();
      unmount();
    }
  });

  it("서버가 next_action 을 주면 그 문장을 그대로 보인다", async () => {
    vi.mocked(api.getJob).mockResolvedValue({ ...example, next_action: { kind: "approve", message: "서버가 정한 문장", count: null } });
    renderWithQuery(<JobPage jobId="job-0000abcd" />);
    expect(await screen.findByRole("region", { name: "다음 할 일" })).toHaveTextContent("서버가 정한 문장");
  });

  it("불일치가 남으면 승인을 누르기 전에 막고 이유를 보인다", async () => {
    vi.mocked(api.getJob).mockResolvedValue(example);
    renderWithQuery(<JobPage jobId="job-0000abcd" />);
    const banner = await screen.findByRole("region", { name: "다음 할 일" });
    await userEvent.setup().click(within(banner).getByRole("button", { name: "판독 오류면 승인으로" }));
    const notes = await screen.findAllByRole("note");
    expect(notes.some((n) => n.classList.contains("wms-blocked") && n.textContent?.includes("서류를 고쳐 다시 올리거나, 원본을 확인해 판독 오류면 사유를 적고 승인하세요"))).toBe(true);
    expect(screen.getByRole("button", { name: "판독 오류로 승인하고 WMS 등록" })).toBeDisabled();
  });

  it("단계 표시줄: 처음에는 할 일이 있는 단계를 열고, 누르면 그 단계만 보인다", async () => {
    vi.mocked(api.getJob).mockResolvedValue(example); // 불일치가 남음 → 서류 대조
    renderWithQuery(<JobPage jobId="job-7c1e" />);
    const user = userEvent.setup();

    const bar = await screen.findByRole("tablist", { name: "작업 단계" });
    expect(within(bar).getAllByRole("tab")).toHaveLength(5);
    expect(within(bar).getByRole("tab", { name: /서류 대조/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("오류 목록 (1)")).toBeInTheDocument();
    expect(screen.queryByLabelText("승인자")).not.toBeInTheDocument(); // 다른 단계는 숨김

    await user.click(within(bar).getByRole("tab", { name: /WMS 등록/ }));
    expect(screen.getByLabelText("승인자")).toBeInTheDocument();
    expect(screen.queryByText("오류 목록 (1)")).not.toBeInTheDocument();
  });

  it("결과가 나오기 전에는 처리 과정만 누를 수 있다", async () => {
    vi.mocked(api.getJob).mockResolvedValue(at("running", { steps: [example.steps[0]] }));
    renderWithQuery(<JobPage jobId="job-0000abcd" />);
    const bar = await screen.findByRole("tablist", { name: "작업 단계" });
    expect(within(bar).getByRole("tab", { name: /처리 과정/ })).toHaveAttribute("aria-selected", "true");
    expect(within(bar).getByRole("tab", { name: /HS 코드/ })).toBeDisabled();
  });

  it("defaultStage 는 다음 할 일을 따른다", () => {
    const base = example.result!;
    expect(defaultStage(example)).toBe("review");
    const noMismatch = { ...example, next_action: undefined, result: { ...base, issues: [] } };
    expect(defaultStage(noMismatch)).toBe("hs");
    expect(defaultStage({ ...noMismatch, next_action: { kind: "approve", message: "", count: null } })).toBe("wms");
    expect(defaultStage(at("running"))).toBe("process");
  });

  it("stageInfo 는 서버 결과로 단계 상태를 정한다", () => {
    expect(stageInfo(example, "review")).toEqual({ state: "todo", note: "불일치 1건" });
    expect(stageInfo(example, "hs")).toEqual({ state: "todo", note: "1개 고르기" });
    expect(stageInfo(example, "wms")).toEqual({ state: "todo", note: "승인 대기" });
    expect(stageInfo(at("failed"), "process").state).toBe("fail");
  });

  it("groupSteps 는 분류 · 읽기 · 대조 · HS · 마무리로 묶고 빈 묶음은 뺀다", () => {
    const step = (tool: string) => ({ tool, summary: tool, ok: true });
    const groups = groupSteps(["classify_document", "read_document", "ocr_document", "cross_check", "reread_field", "finish_report"].map(step));
    expect(groups.map((g) => [g.label, g.steps.length])).toEqual([
      ["서류 분류", 1],
      ["서류 읽기", 2],
      ["대조와 다시 확인", 2],
      ["마무리", 1],
    ]);
  });
});
