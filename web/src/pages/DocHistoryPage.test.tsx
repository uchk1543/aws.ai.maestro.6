// G10·G11 문서 분류 내역: 종류 고르기 → getDocuments, 서류 카드(원본 | 인식 결과), 좌우 넘기기, 빈 목록, 오류
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

/** 지금 보이는 카드 (나머지는 aria-hidden) */
function currentCard() {
  return screen.getAllByRole("article").find((a) => a.closest("[aria-hidden='true']") === null)!;
}

beforeEach(() => {
  vi.mocked(api.getDocuments).mockReset();
  vi.mocked(api.getJobFiles)
    .mockReset()
    .mockImplementation((jobId) => Promise.resolve({ files: all.filter((d) => d.job_id === jobId).map(fileViewOf) }));
});

describe("DocHistoryPage", () => {
  it("처음에는 상업송장을 불러오고, 종류별 건수는 서버 counts 그대로 보여 준다", async () => {
    vi.mocked(api.getDocuments).mockResolvedValue(page("commercial_invoice"));
    renderWithQuery(<DocHistoryPage />);

    await screen.findByRole("region", { name: "상업송장 서류" });
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

  it("누르지 않아도 첫 서류의 원본과 인식 결과가 바로 보인다", async () => {
    vi.mocked(api.getDocuments).mockResolvedValue(page("commercial_invoice"));
    renderWithQuery(<DocHistoryPage />);

    const card = await screen.findByRole("article", { name: "invoice.pdf" });
    expect(await within(card).findByRole("img", { name: "invoice.pdf 1쪽" })).toBeInTheDocument();
    expect(api.getJobFiles).toHaveBeenCalledWith("job-7c1e");
    expect(card).toHaveTextContent("AI 자동 분류");
    expect(card).toHaveTextContent("제목 COMMERCIAL INVOICE, Unit Price·Amount 칸");
    expect(card).toHaveTextContent("INV-2026-0214");
    expect(card).toHaveTextContent("샘플무역");
    expect(card).toHaveTextContent("승인 대기");
    expect(screen.getByText("1 / 4")).toBeInTheDocument();
  });

  it("근거가 된 곳·읽은 값을 누르면 서류 위 그 박스가 강조된다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDocuments).mockResolvedValue(page("commercial_invoice"));
    renderWithQuery(<DocHistoryPage />);

    const card = await screen.findByRole("article", { name: "invoice.pdf" });
    const reasons = within(await within(card).findByRole("list", { name: "근거가 된 곳" })).getAllByRole("button");
    expect(reasons.map((b) => b.textContent)).toEqual(["제목COMMERCIAL INVOICE", "특징 칸Unit Price", "특징 칸Amount"]);
    await user.click(reasons[1]);
    expect(within(card).getByRole("button", { name: "분류 근거 · 특징 칸: Unit Price" })).toHaveAttribute("aria-pressed", "true");
    expect(within(card).getByRole("dialog", { name: "분류 근거 · 특징 칸" })).toHaveTextContent("Unit Price");

    const values = within(within(card).getByRole("list", { name: "읽은 값" })).getAllByRole("button");
    expect(values[0]).toHaveTextContent("송장 번호INV-2026-0214");
  });

  it("다음·이전 버튼과 ←·→ 키로 서류를 넘긴다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDocuments).mockResolvedValue(page("commercial_invoice"));
    renderWithQuery(<DocHistoryPage />);
    await screen.findByText("1 / 4");
    const prev = screen.getByRole("button", { name: "이전 서류" });
    expect(prev).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "다음 서류" }));
    expect(screen.getByText("2 / 4")).toBeInTheDocument();
    expect(currentCard()).toHaveAccessibleName("invoice_SHE-2026-0213.pdf");

    screen.getByRole("region", { name: "상업송장 서류" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByText("3 / 4")).toBeInTheDocument();
    await user.keyboard("{ArrowLeft}");
    await user.click(prev);
    expect(screen.getByText("1 / 4")).toBeInTheDocument();
    expect(currentCard()).toHaveAccessibleName("invoice.pdf");
  });

  it("마지막 카드에서 다음 쪽이 있으면 next_cursor 로 불러와 넘기고, 끝이면 다음 버튼이 꺼진다", async () => {
    const user = userEvent.setup();
    const invoices = all.filter((d) => d.doc_type === "commercial_invoice");
    vi.mocked(api.getDocuments)
      .mockResolvedValueOnce({ counts, items: invoices.slice(0, 3), next_cursor: "c3" })
      .mockResolvedValueOnce({ counts, items: invoices.slice(3), next_cursor: null });
    renderWithQuery(<DocHistoryPage />);
    const next = await screen.findByRole("button", { name: "다음 서류" });

    await user.click(next);
    await user.click(next);
    await user.click(next);

    await waitFor(() => expect(screen.getByText("4 / 4")).toBeInTheDocument());
    expect(api.getDocuments).toHaveBeenLastCalledWith("commercial_invoice", "c3");
    expect(currentCard()).toHaveAccessibleName("invoice_EX-2026-0198.pdf");
    expect(next).toBeDisabled();
  });

  it("종류를 바꾸면 그 종류로 다시 부르고 첫 장부터 보여 준다 ('분류 못 함'은 unknown)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDocuments).mockImplementation((t) => Promise.resolve(page(t)));
    renderWithQuery(<DocHistoryPage />);
    await user.click(await screen.findByRole("button", { name: "다음 서류" }));

    await user.click(screen.getByRole("button", { name: /^분류 못 함/ }));

    expect(await screen.findByRole("region", { name: "분류 못 함 서류" })).toBeInTheDocument();
    expect(api.getDocuments).toHaveBeenLastCalledWith("unknown", null);
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(currentCard()).toHaveAccessibleName("scan_0001.jpg");
  });

  it("'작업 화면 열기'는 그 작업으로 간다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDocuments).mockResolvedValue(page("unknown"));
    renderWithQuery(<DocHistoryPage />);

    const card = await screen.findByRole("article", { name: "scan_0001.jpg" });
    await user.click(within(card).getByRole("button", { name: "작업 화면 열기" }));
    expect(window.location.hash).toBe("#/jobs/job-51bd");
  });

  it("서버에 서류 보기 경로가 없으면(404) 오류 대신 '준비 중'으로 두고 분류 결과만 보여 준다", async () => {
    vi.mocked(api.getDocuments).mockResolvedValue(page("unknown"));
    vi.mocked(api.getJobFiles).mockRejectedValue(new api.ApiError(404, "없는 경로입니다"));
    renderWithQuery(<DocHistoryPage />);

    const card = await screen.findByRole("article", { name: "scan_0001.jpg" });
    expect(await within(card).findByText("원본 보기는 준비 중입니다.")).toBeInTheDocument();
    expect(within(card).queryByRole("alert")).not.toBeInTheDocument();
    expect(card).not.toHaveTextContent("없는 경로입니다");
    expect(card).toHaveTextContent("제목이 가려져 있고 칸만으로 종류를 정할 수 없음");
  });

  it("그 밖의 오류는 서버 문장을 보여 준다", async () => {
    vi.mocked(api.getDocuments).mockResolvedValue(page("unknown"));
    vi.mocked(api.getJobFiles).mockRejectedValue(new api.ApiError(500, "S3 주소를 만들지 못했습니다"));
    renderWithQuery(<DocHistoryPage />);

    const card = await screen.findByRole("article", { name: "scan_0001.jpg" });
    expect(await within(card).findByRole("alert")).toHaveTextContent("서류 원본을 불러오지 못했습니다: S3 주소를 만들지 못했습니다");
  });

  it("서류의 박스를 누르면 그 자리에 무엇을 읽었는지 작은 팝업이 뜨고, 닫기로 닫힌다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDocuments).mockResolvedValue(page("commercial_invoice"));
    renderWithQuery(<DocHistoryPage />);
    const card = await screen.findByRole("article", { name: "invoice.pdf" });

    await user.click(await within(card).findByRole("button", { name: "분류 근거 · 제목: COMMERCIAL INVOICE" }));
    const pop = within(card).getByRole("dialog", { name: "분류 근거 · 제목" });
    expect(pop).toHaveTextContent("COMMERCIAL INVOICE");
    expect(pop).toHaveTextContent("제목 COMMERCIAL INVOICE, Unit Price·Amount 칸");

    await user.click(within(card).getByRole("button", { name: "읽은 값 · 송장 번호: INV-2026-0214" }));
    expect(within(card).getByRole("dialog", { name: "읽은 값 · 송장 번호" })).toHaveTextContent("INV-2026-0214");

    await user.click(within(card).getByRole("button", { name: "팝업 닫기" }));
    expect(within(card).queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("빈 목록이면 없다고 알린다", async () => {
    vi.mocked(api.getDocuments).mockResolvedValue({ counts, items: [], next_cursor: null });
    renderWithQuery(<DocHistoryPage />);

    expect(await screen.findByText("이 종류로 분류된 서류가 없습니다.")).toBeInTheDocument();
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "다음 서류" })).not.toBeInTheDocument();
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
});
