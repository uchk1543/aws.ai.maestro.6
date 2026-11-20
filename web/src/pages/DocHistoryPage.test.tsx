// G10 문서 분류 내역: 종류 고르기 → getDocuments, 표의 열·값, 작업 이동, 빈 목록, 오류, 더 보기
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import draft from "../fixtures/documents.draft.json";
import { fileViewOf } from "../mockDocs";
import { renderWithQuery } from "../test-utils";
import type { DocType, DocumentRecord, DocumentsResponse } from "../types";
import { DocHistoryPage } from "./DocHistoryPage";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, getDocuments: vi.fn(), getJobFiles: vi.fn() };
});

const counts = draft.counts as Record<DocType, number>;
const all = draft.items as DocumentRecord[];
const page = (docType: DocType, next: string | null = null): DocumentsResponse => ({
  counts,
  items: all.filter((d) => d.doc_type === docType),
  next_cursor: next,
});

beforeEach(() => {
  vi.mocked(api.getDocuments).mockReset();
  vi.mocked(api.getJobFiles).mockReset();
});

describe("DocHistoryPage", () => {
  it("처음에는 상업송장을 불러오고, 종류별 건수는 서버 counts 그대로 보여 준다", async () => {
    vi.mocked(api.getDocuments).mockResolvedValue(page("commercial_invoice"));
    renderWithQuery(<DocHistoryPage />);

    await screen.findByText("invoice.pdf");
    expect(api.getDocuments).toHaveBeenCalledWith("commercial_invoice", null);
    const kinds = within(screen.getByRole("list", { name: "서류 종류" })).getAllByRole("button");
    expect(kinds.map((k) => k.textContent)).toEqual([
      "상업송장4건",
      "포장명세서3건",
      "선하증권2건",
      "원산지증명서1건",
      "분류 못 함2건",
    ]);
    expect(kinds[0]).toHaveAttribute("aria-pressed", "true");
  });

  it("표에 파일·작업·서류 번호·수하인·근거·분류한 쪽·상태·날짜를 서버 값 그대로 보여 준다", async () => {
    vi.mocked(api.getDocuments).mockResolvedValue(page("commercial_invoice"));
    renderWithQuery(<DocHistoryPage />);

    await screen.findByText("invoice.pdf");
    const headers = within(screen.getByRole("table")).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["파일 이름", "작업", "서류 번호", "수하인", "분류 근거", "분류", "작업 상태", "올린 날짜"]);

    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(4);
    const first = within(rows[0]).getAllByRole("cell").map((c) => c.textContent);
    expect(first).toEqual([
      "invoice.pdf",
      "job-7c1e",
      "INV-2026-0214",
      "샘플무역",
      "제목 COMMERCIAL INVOICE, Unit Price·Amount 칸",
      "자동",
      "승인 대기",
      "2026-11-20 14:03",
    ]);
    // 읽기 전이라 번호·수하인이 없으면 "-", 사용자가 고른 종류는 "사용자 선택"
    const third = within(rows[2]).getAllByRole("cell").map((c) => c.textContent);
    expect(third.slice(2, 4)).toEqual(["-", "-"]);
    expect(third[5]).toBe("사용자 선택");
    // 모바일 카드에서 칸 이름으로 쓰는 data-label 이 열 이름과 같다
    expect(within(rows[0]).getAllByRole("cell").map((c) => c.getAttribute("data-label"))).toEqual(headers);
  });

  it("종류를 고르면 그 종류로 다시 부르고, '분류 못 함'은 unknown 이다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDocuments).mockImplementation((t) => Promise.resolve(page(t)));
    renderWithQuery(<DocHistoryPage />);
    await screen.findByText("invoice.pdf");

    await user.click(screen.getByRole("button", { name: /^분류 못 함/ }));

    expect(await screen.findByText("merged_docs.pdf")).toBeInTheDocument();
    expect(api.getDocuments).toHaveBeenLastCalledWith("unknown", null);
    expect(screen.getByText("분류 실패: 서류 여러 장이 한 파일에 합쳐져 있음")).toBeInTheDocument();
    expect(screen.queryByText("invoice.pdf")).not.toBeInTheDocument();
  });

  it("작업 번호를 누르면 그 작업 화면으로 간다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDocuments).mockResolvedValue(page("unknown"));
    renderWithQuery(<DocHistoryPage />);

    await user.click(await screen.findByRole("button", { name: "job-c442" }));
    expect(window.location.hash).toBe("#/jobs/job-c442");
  });

  it("빈 목록이면 없다고 알린다", async () => {
    vi.mocked(api.getDocuments).mockResolvedValue({ counts, items: [], next_cursor: null });
    renderWithQuery(<DocHistoryPage />);

    expect(await screen.findByText("이 종류로 분류된 서류가 없습니다.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "더 보기" })).not.toBeInTheDocument();
  });

  it("서버 오류 문장을 보여 주고, 404·501 이면 준비 중이라고 덧붙인다", async () => {
    vi.mocked(api.getDocuments).mockRejectedValue(new api.ApiError(404, "없는 경로입니다 (GET /documents)"));
    const { unmount } = renderWithQuery(<DocHistoryPage />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("없는 경로입니다 (GET /documents)");
    expect(alert).toHaveTextContent("아직 준비되지 않았습니다");
    unmount();

    vi.mocked(api.getDocuments).mockRejectedValue(new api.ApiError(500, "조회에 실패했습니다"));
    renderWithQuery(<DocHistoryPage />);
    const other = await screen.findByRole("alert");
    expect(other).toHaveTextContent("조회에 실패했습니다");
    expect(other).not.toHaveTextContent("아직 준비되지 않았습니다");
  });

  it("next_cursor 가 있을 때만 '더 보기'가 있고, 누르면 그 cursor 로 다음 쪽을 붙인다", async () => {
    const user = userEvent.setup();
    const invoices = all.filter((d) => d.doc_type === "commercial_invoice");
    vi.mocked(api.getDocuments)
      .mockResolvedValueOnce({ counts, items: invoices.slice(0, 3), next_cursor: "c3" })
      .mockResolvedValueOnce({ counts, items: invoices.slice(3), next_cursor: null });
    renderWithQuery(<DocHistoryPage />);

    await user.click(await screen.findByRole("button", { name: "더 보기" }));

    await waitFor(() => expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(1 + 4));
    expect(api.getDocuments).toHaveBeenLastCalledWith("commercial_invoice", "c3");
    expect(screen.queryByRole("button", { name: "더 보기" })).not.toBeInTheDocument();
  });
  it("파일 이름을 누르면 서류 그림과 분류 근거 창이 열리고, 근거를 누르면 그 박스가 강조된다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDocuments).mockResolvedValue(page("commercial_invoice"));
    vi.mocked(api.getJobFiles).mockImplementation((jobId) =>
      Promise.resolve({ files: all.filter((d) => d.job_id === jobId).map(fileViewOf) }),
    );
    renderWithQuery(<DocHistoryPage />);

    await user.click(await screen.findByRole("button", { name: "invoice.pdf" }));

    const dialog = screen.getByRole("dialog", { name: "invoice.pdf" });
    expect(api.getJobFiles).toHaveBeenCalledWith("job-7c1e");
    expect(await within(dialog).findByRole("img", { name: "invoice.pdf 1쪽" })).toBeInTheDocument();
    expect(dialog).toHaveTextContent("AI 자동 분류");
    expect(dialog).toHaveTextContent("제목 COMMERCIAL INVOICE, Unit Price·Amount 칸");

    const reasons = within(within(dialog).getByRole("list", { name: "근거가 된 곳" })).getAllByRole("button");
    expect(reasons.map((b) => b.textContent)).toEqual(["제목COMMERCIAL INVOICE", "특징 칸Unit Price", "특징 칸Amount"]);
    await user.click(reasons[1]);
    expect(within(dialog).getByRole("button", { name: "분류 근거 · 특징 칸: Unit Price" })).toHaveAttribute("aria-pressed", "true");

    const values = within(within(dialog).getByRole("list", { name: "읽은 값" })).getAllByRole("button");
    expect(values[0]).toHaveTextContent("송장 번호INV-2026-0214");
  });

  it("창은 닫기 버튼과 Esc 로 닫히고, '작업 화면 열기'는 그 작업으로 간다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDocuments).mockResolvedValue(page("unknown"));
    vi.mocked(api.getJobFiles).mockRejectedValue(new api.ApiError(404, "없는 경로입니다"));
    renderWithQuery(<DocHistoryPage />);

    await user.click(await screen.findByRole("button", { name: "merged_docs.pdf" }));
    const dialog = screen.getByRole("dialog");
    // 서버가 그림을 주지 않아도 분류 결과는 보인다
    expect(await within(dialog).findByText(/서류 그림을 불러오지 못했습니다/)).toBeInTheDocument();
    expect(dialog).toHaveTextContent("분류 실패: 서류 여러 장이 한 파일에 합쳐져 있음");

    await user.click(within(dialog).getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "merged_docs.pdf" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "merged_docs.pdf" }));
    await user.click(screen.getByRole("button", { name: "작업 화면 열기" }));
    expect(window.location.hash).toBe("#/jobs/job-c442");
  });
});
