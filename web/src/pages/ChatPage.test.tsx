// G8 현황 채팅: 답·조건·표, session_id 유지, 오류 표시
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import chatExample from "../../../docs/examples/chat_response.json";
import * as api from "../api";
import { renderWithQuery } from "../test-utils";
import type { ChatResponse } from "../types";
import { ChatPage, chatSessionId, describeFilters } from "./ChatPage";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, sendChat: vi.fn() };
});

const example = chatExample as ChatResponse;

beforeEach(() => {
  vi.mocked(api.sendChat).mockReset();
  sessionStorage.clear();
});

describe("ChatPage", () => {
  it("질문을 보내면 예시의 답·조건·표를 보여 준다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.sendChat).mockResolvedValue(example);
    renderWithQuery(<ChatPage />);

    await user.type(screen.getByLabelText("질문"), "이번 주 통관 지연 건은?");
    await user.click(screen.getByRole("button", { name: "보내기" }));

    expect(await screen.findByText(example.answer)).toBeInTheDocument();
    expect(screen.getByText("이번 주 통관 지연 건은?")).toBeInTheDocument();
    expect(screen.getByText(/조회 조건: 상태: 통관 지연 · 기간: 이번 주 \(2026-11-16 ~ 2026-11-22\) · 1건/)).toBeInTheDocument();

    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("BL-2026-0001");
    expect(rows[0]).toHaveTextContent("샘플무역");
    expect(rows[0]).toHaveTextContent("심사 중");
    expect(screen.getByLabelText("질문")).toHaveValue("");
  });

  it("같은 탭에서는 같은 session_id 로 보낸다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.sendChat).mockResolvedValue(example);
    renderWithQuery(<ChatPage />);

    await user.type(screen.getByLabelText("질문"), "오늘 들어온 건");
    await user.click(screen.getByRole("button", { name: "보내기" }));
    await screen.findByText(example.answer);
    await user.type(screen.getByLabelText("질문"), "지난주는?");
    await user.click(screen.getByRole("button", { name: "보내기" }));

    await waitFor(() => expect(api.sendChat).toHaveBeenCalledTimes(2));
    const [first, second] = vi.mocked(api.sendChat).mock.calls.map((c) => c[0]);
    expect(first).toEqual({ session_id: chatSessionId(), message: "오늘 들어온 건" });
    expect(second.session_id).toBe(first.session_id);
  });

  it("작업 번호를 누르면 그 작업 화면으로 간다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.sendChat).mockResolvedValue(example);
    renderWithQuery(<ChatPage />);

    await user.type(screen.getByLabelText("질문"), "지연 건");
    await user.click(screen.getByRole("button", { name: "보내기" }));
    await user.click(await screen.findByRole("button", { name: "job-7c1e" }));

    expect(window.location.hash).toBe("#/jobs/job-7c1e");
  });

  it("서버 오류 문장을 보여 준다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.sendChat).mockRejectedValue(new api.ApiError(501, "아직 만들지 않은 경로입니다 (E5)"));
    renderWithQuery(<ChatPage />);

    await user.type(screen.getByLabelText("질문"), "이번 주");
    await user.click(screen.getByRole("button", { name: "보내기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("아직 만들지 않은 경로입니다 (E5)");
  });

  it("빈 질문은 보낼 수 없다", async () => {
    const user = userEvent.setup();
    renderWithQuery(<ChatPage />);

    await user.type(screen.getByLabelText("질문"), "   ");
    expect(screen.getByRole("button", { name: "보내기" })).toBeDisabled();
  });

  it("0건이면 표 없이 0건과 조건을 보여 준다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.sendChat).mockResolvedValue({ ...example, answer: "0건입니다.", rows: [] });
    renderWithQuery(<ChatPage />);

    await user.type(screen.getByLabelText("질문"), "이번 주 통관 지연");
    await user.click(screen.getByRole("button", { name: "보내기" }));

    expect(await screen.findByText(/· 0건/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("describeFilters", () => {
  it("조건이 없으면 빈 목록", () => {
    expect(describeFilters({ ...example, filters: { status: null, period: null }, period_resolved: null })).toEqual([]);
  });
});
