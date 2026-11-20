// G8·G9 현황 채팅: 답·조건·표, 예시 질문, session_id 유지, 오류 표시
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import chatExample from "../../../docs/examples/chat_response.json";
import * as api from "../api";
import { renderWithQuery } from "../test-utils";
import type { ChatResponse } from "../types";
import { ChatPage, chatSessionId, describeFilters, EXAMPLES } from "./ChatPage";

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

    await user.type(screen.getByLabelText("질문"), "이번 주 지연 건 알려줘");
    await user.click(screen.getByRole("button", { name: "보내기" }));

    expect(await screen.findByText(example.answer)).toBeInTheDocument();
    expect(screen.getByText("이번 주 지연 건 알려줘")).toBeInTheDocument();
    const conds = within(screen.getByRole("list", { name: "조회 조건" })).getAllByRole("listitem");
    expect(conds.map((c) => c.textContent)).toEqual(["상태: 통관 지연", "기간: 이번 주 (2026-11-16 ~ 2026-11-22)", "1건"]);

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

    expect(await screen.findByText("0건")).toBeInTheDocument();
    expect(screen.getByText("상태: 통관 지연")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("예시 질문을 누르면 그 질문을 바로 보낸다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.sendChat).mockResolvedValue(example);
    renderWithQuery(<ChatPage />);

    const examples = within(screen.getByRole("list", { name: "예시 질문" })).getAllByRole("button");
    expect(examples.map((b) => b.textContent)).toEqual(EXAMPLES);
    await user.click(examples[0]);

    await waitFor(() => expect(api.sendChat).toHaveBeenCalledWith({ session_id: chatSessionId(), message: EXAMPLES[0] }));
    expect(await screen.findByText(example.answer)).toBeInTheDocument();
  });

  it("조건이 없으면 '조건 없음'", async () => {
    const user = userEvent.setup();
    vi.mocked(api.sendChat).mockResolvedValue({ ...example, filters: { status: null, period: null }, period_resolved: null });
    renderWithQuery(<ChatPage />);

    await user.type(screen.getByLabelText("질문"), "전체 화물");
    await user.click(screen.getByRole("button", { name: "보내기" }));

    expect(await screen.findByText("조건 없음")).toBeInTheDocument();
  });
});

describe("describeFilters", () => {
  it("조건이 없으면 빈 목록", () => {
    expect(describeFilters({ ...example, filters: { status: null, period: null }, period_resolved: null })).toEqual([]);
  });

  it("주소로 온 질문(대시보드)을 열릴 때 한 번 보내고, 주소에서 뺀다", async () => {
    vi.mocked(api.sendChat).mockResolvedValue(example);
    window.location.hash = "#/chat?q=x";
    renderWithQuery(<ChatPage ask="지금 통관이 늦어지고 있는 화물 전부 보여줘" />);

    expect(await screen.findByText(example.answer)).toBeInTheDocument();
    expect(api.sendChat).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.sendChat).mock.calls[0][0].message).toBe("지금 통관이 늦어지고 있는 화물 전부 보여줘");
    expect(window.location.hash).toBe("#/chat");
  });

  it("입력칸 아래에 질문마다 따로 답한다는 안내를 둔다 (서버는 앞 질문을 기억하지 않는다, FB09)", () => {
    renderWithQuery(<ChatPage />);
    const note = screen.getByText("질문마다 따로 답합니다. 조건을 한 문장에 모두 적어 주세요");
    expect(screen.getByRole("textbox", { name: "질문" })).toHaveAccessibleDescription(note.textContent!);
  });
});
