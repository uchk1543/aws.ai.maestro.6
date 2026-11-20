// #281 작업 내역: 작업(서류를 올린 묶음)마다 카드 한 장. 올린 서류·분류, 걸러낸 문제·근거, 다음 할 일, 거르기
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import * as route from "../route";
import { renderWithQuery } from "../test-utils";
import type { JobListResponse, JobSummary } from "../types";
import { DocHistoryPage, filtersOf } from "./DocHistoryPage";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, getJobHistory: vi.fn() };
});

const mismatchJob: JobSummary = {
  job_id: "job-7c1e",
  status: "waiting_approval",
  bl_no: "BL-2026-0001",
  consignee: "샘플무역",
  created_at: "2026-11-20 14:05",
  next_action: { kind: "fix_docs", message: "불일치 1건: 서류를 고쳐 다시 올리거나, 원본을 확인해 판독 오류면 사유를 적고 승인하세요", count: 1 },
  mismatch: 1,
  hs_pending: 1,
  check: 1,
  docs: [
    { file_name: "invoice.pdf", doc_type: "commercial_invoice", classified_by: "model" },
    { file_name: "scan.jpg", doc_type: "unknown", classified_by: "model" },
    { file_name: "pl.pdf", doc_type: "packing_list", classified_by: "user" },
  ],
  issues: [{ grade: "불일치", rule_id: "X-WT-01", evidence: "상업송장 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다." }],
};
const cleanJob: JobSummary = {
  job_id: "job-3a90",
  status: "done",
  bl_no: null,
  consignee: null,
  created_at: "2026-11-20 11:40",
  next_action: { kind: "none", message: "WMS에 등록됐습니다. 더 할 일이 없습니다", count: null },
  mismatch: 0,
  hs_pending: 0,
  check: 0,
  docs: [{ file_name: "invoice.pdf", doc_type: "commercial_invoice", classified_by: "model" }],
  issues: [],
};
const response = (items: JobSummary[], total = items.length): JobListResponse => ({ items, total });

beforeEach(() => {
  vi.mocked(api.getJobHistory).mockReset().mockResolvedValue(response([mismatchJob, cleanJob]));
});

describe("DocHistoryPage (작업 내역)", () => {
  it("작업마다 카드 한 장: B/L·수입자·상태·올린 시각, 서류와 분류 결과", async () => {
    renderWithQuery(<DocHistoryPage />);
    const card = await screen.findByRole("article", { name: "작업 job-7c1e" });
    expect(within(card).getByText("BL-2026-0001")).toBeInTheDocument();
    expect(within(card).getByText("샘플무역")).toBeInTheDocument();
    expect(within(card).getByText("승인 대기")).toBeInTheDocument();
    expect(card).toHaveTextContent("2026-11-20 14:05");

    const docs = within(within(card).getByRole("region", { name: "올린 서류" })).getAllByRole("listitem");
    expect(docs.map((d) => d.textContent)).toEqual(["상업송장invoice.pdf", "분류 못 함scan.jpg", "포장명세서pl.pdf직접 고름"]);
    expect(api.getJobHistory).toHaveBeenCalledWith({});
  });

  it("문제 한 줄: 첫 문제의 등급과 근거 문장, 나머지는 '외 N건' (건수는 서버 값)", async () => {
    renderWithQuery(<DocHistoryPage />);
    const card = await screen.findByRole("article", { name: "작업 job-7c1e" });
    const problem = within(card).getByLabelText("문제");
    expect(problem).toHaveTextContent("불일치상업송장 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다.");
    expect(problem).toHaveTextContent("외 1건"); // 불일치 1 + 확인 필요 1 - 보인 1
  });

  it("문제가 없는 끝난 작업은 '없음 ✔', 할 일도 '없음'", async () => {
    renderWithQuery(<DocHistoryPage />);
    const card = await screen.findByRole("article", { name: "작업 job-3a90" });
    expect(within(card).getByLabelText("문제")).toHaveTextContent("없음 ✔");
    expect(within(card).getByLabelText("할 일")).toHaveTextContent("없음");
    expect(within(card).getByText("B/L 번호 없음")).toBeInTheDocument();
  });

  it("할 일은 다음 할 일 종류의 짧은 문구(서버 문장은 title), '작업 보기'는 그 작업 화면으로 간다", async () => {
    const go = vi.spyOn(route, "navigate").mockImplementation(() => {});
    renderWithQuery(<DocHistoryPage />);
    const card = await screen.findByRole("article", { name: "작업 job-7c1e" });
    const todo = within(card).getByLabelText("할 일");
    expect(todo).toHaveTextContent("서류 고쳐 다시 올리기판독 오류면 사유 적고 승인");
    expect(within(todo).getByText("서류 고쳐 다시 올리기")).toHaveAttribute("title", mismatchJob.next_action.message);
    await userEvent.setup().click(within(card).getByRole("button", { name: "작업 보기" }));
    expect(go).toHaveBeenCalledWith("/jobs/job-7c1e");
    go.mockRestore();
  });

  it("건수는 서버 total, 50건을 넘으면 최근 것만 보인다고 알린다", async () => {
    vi.mocked(api.getJobHistory).mockResolvedValue(response([mismatchJob], 73));
    renderWithQuery(<DocHistoryPage />);
    expect(await screen.findByText("최근 1건만 보입니다.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("전체 73건");
  });

  it("보기 칩은 대시보드와 같은 조건으로 주소를 바꾼다", async () => {
    const go = vi.spyOn(route, "navigate").mockImplementation(() => {});
    renderWithQuery(<DocHistoryPage />);
    await screen.findByRole("article", { name: "작업 job-7c1e" });
    await userEvent.setup().click(screen.getByRole("button", { name: /불일치/, pressed: false }));
    expect(go).toHaveBeenCalledWith("/documents", { job_status: "waiting_approval", grade: "불일치" });
    go.mockRestore();
  });

  it("주소의 거르기(대시보드에서 옴)를 서버에 넘기고, 맞는 보기 칩을 켠다", async () => {
    renderWithQuery(<DocHistoryPage params={{ job_status: "waiting_approval", hs: "pending" }} />);
    await screen.findByRole("article", { name: "작업 job-7c1e" });
    expect(api.getJobHistory).toHaveBeenCalledWith({ job_status: "waiting_approval", hs: "pending" });
    expect(screen.getByRole("button", { name: /HS 고를 것/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("규칙·종류 거르기는 칩으로 보이고 지우면 전체로 간다", async () => {
    const go = vi.spyOn(route, "navigate").mockImplementation(() => {});
    renderWithQuery(<DocHistoryPage params={{ rule_id: "X-WT-01", type: "unknown" }} />);
    const chips = await screen.findByLabelText("거르기");
    expect(chips).toHaveTextContent("규칙 X-WT-01");
    expect(chips).toHaveTextContent("분류 못 함 서류가 있는 작업");
    await userEvent.setup().click(within(chips).getByRole("button", { name: "거르기 지우기" }));
    expect(go).toHaveBeenCalledWith("/documents", {});
    go.mockRestore();
  });

  it("빈 목록과 서버 오류를 알린다", async () => {
    vi.mocked(api.getJobHistory).mockResolvedValueOnce(response([]));
    const { unmount } = renderWithQuery(<DocHistoryPage />);
    expect(await screen.findByText("조건에 맞는 작업이 없습니다.")).toBeInTheDocument();
    unmount();
    vi.mocked(api.getJobHistory).mockRejectedValueOnce(new api.ApiError(502, "작업 목록을 읽지 못했습니다"));
    renderWithQuery(<DocHistoryPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("작업 목록을 읽지 못했습니다");
  });

  it("filtersOf 는 값 목록 밖의 값을 버린다", () => {
    expect(filtersOf({ job_status: "late", grade: "나쁨", hs: "done", type: "memo", rule_id: "X WT" })).toEqual({});
    expect(filtersOf({ job_status: "done", grade: "확인 필요", hs: "pending", type: "unknown", rule_id: "X-WT-01" })).toEqual({
      job_status: "done",
      grade: "확인 필요",
      hs: "pending",
      type: "unknown",
      rule_id: "X-WT-01",
    });
  });
});
