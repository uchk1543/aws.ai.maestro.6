// G8·G9 현황 채팅: 답·조건·표, 예시 질문, session_id 유지, 오류 표시
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import historyExample from "../../../docs/examples/chat_history.json";
import chatChartExample from "../../../docs/examples/chat_chart_response.json";
import chatExample from "../../../docs/examples/chat_response.json";
import * as api from "../api";
import { renderWithQuery } from "../test-utils";
import type { ChatHistoryResponse, ChatResponse } from "../types";
import { ticks } from "../components/ChatChart";
import { CHAT_NOTE, ChatPage, chatSessionId, describeFilters, EXAMPLES, historyToMessages } from "./ChatPage";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, sendChat: vi.fn(), getChatHistory: vi.fn() };
});

const example = chatExample as ChatResponse;

const history = historyExample as unknown as ChatHistoryResponse;

beforeEach(() => {
  vi.mocked(api.sendChat).mockReset();
  // 기본은 서버에 기록 경로가 없는 것처럼 (메모리만 쓴다)
  vi.mocked(api.getChatHistory).mockReset().mockRejectedValue(new api.ApiError(404, "없는 경로입니다"));
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

  it("열 때 서버 기록을 불러와 그린다: 막힌 답은 회색 안내, 지난 답은 건수만 (G14)", async () => {
    vi.mocked(api.getChatHistory).mockResolvedValue(history);
    renderWithQuery(<ChatPage />);

    expect(await screen.findByText("이번 주 통관 지연 건 알려줘")).toBeInTheDocument();
    expect(api.getChatHistory).toHaveBeenCalledWith(chatSessionId());
    const answer = screen.getByText(/이번 주\(11\/16~11\/22\) 통관 지연 건은 1건입니다/).closest(".chat-answer")!;
    expect(within(answer as HTMLElement).getByText("1건")).toBeInTheDocument();
    expect(answer).toHaveTextContent("지난 대화라 결과 표는 없습니다");
    const blocked = screen.getByText(/통관·화물 현황 질문만 답합니다/).closest(".chat-answer")!;
    expect(blocked).toHaveClass("blocked");
    expect(blocked).toHaveTextContent("안내 · 무관한 질문");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("서버에 기록 경로가 없으면(404) 이 탭의 메모리 대화를 그대로 쓴다", async () => {
    sessionStorage.setItem("team06-chat-messages", JSON.stringify([{ role: "user", text: "메모리에 있던 질문" }]));
    renderWithQuery(<ChatPage />);
    await waitFor(() => expect(api.getChatHistory).toHaveBeenCalled());
    expect(screen.getByText("메모리에 있던 질문")).toBeInTheDocument();
    expect(screen.queryByText(/지난 대화를 불러오지 못해/)).not.toBeInTheDocument();
  });

  it("새 대화를 누르면 대화를 비우고 새 session_id 로 묻는다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getChatHistory).mockResolvedValue(history);
    renderWithQuery(<ChatPage />);
    await screen.findByText("이번 주 통관 지연 건 알려줘");
    const before = chatSessionId();

    vi.mocked(api.getChatHistory).mockResolvedValue({ messages: [] });
    await user.click(screen.getByRole("button", { name: "새 대화" }));

    expect(screen.queryByText("이번 주 통관 지연 건 알려줘")).not.toBeInTheDocument();
    expect(chatSessionId()).not.toBe(before);
    await waitFor(() => expect(api.getChatHistory).toHaveBeenLastCalledWith(chatSessionId()));

    vi.mocked(api.sendChat).mockResolvedValue(example);
    await user.click(screen.getByRole("button", { name: EXAMPLES[0] }));
    await screen.findByText(example.answer);
    expect(vi.mocked(api.sendChat).mock.calls[0][0].session_id).toBe(chatSessionId());
  });

  it("질문을 보낸 뒤 늦게 온 기록으로 대화를 덮지 않는다", async () => {
    const user = userEvent.setup();
    let resolve!: (v: ChatHistoryResponse) => void;
    vi.mocked(api.getChatHistory).mockReturnValue(new Promise((r) => (resolve = r)));
    vi.mocked(api.sendChat).mockResolvedValue(example);
    renderWithQuery(<ChatPage />);

    await user.click(screen.getByRole("button", { name: EXAMPLES[1] }));
    await screen.findByText(example.answer);
    resolve(history);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByText(EXAMPLES[1], { selector: ".chat-user" })).toBeInTheDocument();
    expect(screen.queryByText("오늘 점심 메뉴 추천해 줘")).not.toBeInTheDocument();
  });

  it("historyToMessages 는 질문·답 줄을 대화로 바꾼다", () => {
    const msgs = historyToMessages(history.messages);
    expect(msgs.map((m) => m.role)).toEqual(["user", "assistant", "user", "assistant"]);
    const last = msgs[3];
    expect(last.role === "assistant" && last.response.blocked).toBe("무관한 질문");
  });

  it("입력칸 아래에 앞 질문을 이어 물을 수 있다는 안내를 둔다 (#257 현황 Agent)", () => {
    renderWithQuery(<ChatPage />);
    const note = screen.getByText(CHAT_NOTE);
    expect(note).toHaveTextContent("이어 물을 수 있습니다");
    expect(screen.getByRole("textbox", { name: "질문" })).toHaveAccessibleDescription(note.textContent!);
  });

  it("그래프는 서버 값 그대로 그리고, 아래에 같은 값의 표를 둔다 (#257)", async () => {
    const user = userEvent.setup();
    const res = chatChartExample as ChatResponse;
    vi.mocked(api.sendChat).mockResolvedValue(res);
    renderWithQuery(<ChatPage />);

    await user.click(screen.getByRole("button", { name: EXAMPLES[3] }));
    const figure = await screen.findByRole("figure", { name: `${res.chart!.title} 막대그래프` });
    const table = within(figure).getByRole("table");
    expect(within(table).getAllByRole("row").map((r) => r.textContent)).toEqual(["수입자건수", "샘플무역2", "이그잼플유통1"]);
    expect(figure.querySelectorAll("rect.chart-bar")).toHaveLength(2);
    // 조건 칩에 이번 달 기간
    const conds = within(screen.getByRole("list", { name: "조회 조건" })).getAllByRole("listitem");
    expect(conds.map((c) => c.textContent)).toEqual(["상태: 통관 지연", "기간: 이번 달 (2026-11-01 ~ 2026-11-30)", "3건"]);
  });

  it("선·원 그래프도 그린다. 그래프가 없는 답에는 그리지 않는다", async () => {
    const user = userEvent.setup();
    const base = chatChartExample as ChatResponse;
    vi.mocked(api.sendChat)
      .mockResolvedValueOnce({ ...base, chart: { ...base.chart!, type: "line" } })
      .mockResolvedValueOnce({ ...base, chart: { ...base.chart!, type: "pie" } })
      .mockResolvedValueOnce(example);
    renderWithQuery(<ChatPage />);

    await user.click(screen.getByRole("button", { name: EXAMPLES[3] }));
    const line = await screen.findByRole("figure", { name: /선 그래프$/ });
    expect(line.querySelector("path.chart-line")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: EXAMPLES[3] }));
    const pie = await screen.findByRole("figure", { name: /원 그래프$/ });
    expect(pie.querySelectorAll("path.chart-slice")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: EXAMPLES[0] }));
    await screen.findByText(example.answer);
    expect(screen.getAllByRole("figure")).toHaveLength(2);
  });

  it("답에 작업 ID 가 있고 표에 없으면 작업 화면으로 가는 버튼을 둔다 (#257 get_job)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.sendChat).mockResolvedValue({
      answer: "작업 job-1a2b3c4d에서 불일치 1건이 있었습니다.",
      filters: { status: null, period: null },
      period_resolved: null,
      rows: [],
      blocked: null,
      chart: null,
    });
    window.location.hash = "#/chat";
    renderWithQuery(<ChatPage />);

    await user.click(screen.getByRole("button", { name: EXAMPLES[0] }));
    await user.click(await screen.findByRole("button", { name: /작업 화면 열기 · job-1a2b3c4d/ }));
    expect(window.location.hash).toBe("#/jobs/job-1a2b3c4d");
  });

  it("ticks 는 0 부터 최댓값을 덮는 정수 눈금", () => {
    expect(ticks(0)).toEqual([0]);
    expect(ticks(3)).toEqual([0, 1, 2, 3]);
    expect(ticks(11)).toEqual([0, 3, 6, 9, 12]);
  });
});
