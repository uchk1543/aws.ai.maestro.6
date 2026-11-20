// G8·G9 현황 채팅: POST /api/chat. 답마다 답 문장·조회 조건·결과 표를 보여 준다.
// 조회·집계·기간 계산은 서버 코드가 한다. 화면은 받은 값을 그대로 보여 준다 (agent-design.md 9번).
// 처음에는 예시 질문 칸을 보여 주고, 누르면 그 질문을 바로 보낸다. PC 는 예시를 왼쪽에 늘 둔다.
// G14: 열 때 서버 기록(GET /api/chat/{session_id}, E6 #157)을 불러와 새로 고쳐도 대화가 남는다.
//      서버 경로가 없으면(404·501) 이 탭의 메모리(sessionStorage)만 쓴다. "새 대화"는 새 session_id.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiError, getChatHistory, sendChat } from "../api";
import { Icon } from "../components/Icon";
import { navigate } from "../route";
import type { ChatHistoryLine, ChatResponse, Period } from "../types";

const SESSION_KEY = "team06-chat-session";
const MESSAGES_KEY = "team06-chat-messages";
export const MAX_MESSAGE = 500;

// 예시 질문 (eval/queries.csv 의 질문 모양을 따른다)
export const EXAMPLES = ["이번 주 통관 지연 건은?", "오늘 입항한 화물", "심사 중인 화물", "지난주 입항 화물"];

const PERIOD_KO: Record<Period, string> = {
  today: "오늘",
  this_week: "이번 주",
  last_week: "지난주",
  range: "기간 지정",
};

/** restored: 서버 기록에서 불러온 답. 기록에는 결과 표(rows)가 없고 건수(count)만 있다 */
export type ChatMessage =
  | { role: "user"; text: string }
  | { role: "assistant"; response: ChatResponse; count?: number | null; restored?: boolean };

function newSessionId(): string {
  return typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `s-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** 탭마다 대화 하나. 새로 고쳐도 같은 session_id 를 쓴다. */
export function chatSessionId(): string {
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id = newSessionId();
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

/** 서버 기록 줄 → 화면 대화. 막힌 답은 blocked 에 이유를 넣어 안내 모양으로 그린다. */
export function historyToMessages(lines: ChatHistoryLine[]): ChatMessage[] {
  return lines.map((line) =>
    line.role === "user"
      ? { role: "user", text: line.text }
      : {
          role: "assistant",
          restored: true,
          count: line.count,
          response: {
            answer: line.text,
            filters: line.filters ?? { status: null, period: null },
            period_resolved: null,
            rows: [],
            blocked: line.blocked ? (line.block_reason ?? "막힌 질문") : null,
          },
        },
  );
}

/** 서버에 기록 경로가 아직 없으면(404·501) 메모리만 쓴다 */
function noHistoryRoute(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 404 || e.status === 501);
}

function loadMessages(): ChatMessage[] {
  try {
    const saved = JSON.parse(sessionStorage.getItem(MESSAGES_KEY) ?? "[]");
    return Array.isArray(saved) ? saved : [];
  } catch {
    return [];
  }
}

/** 조회 조건을 사람이 읽는 줄로 바꾼다. 기간은 서버가 계산한 날짜(period_resolved)를 쓴다. */
export function describeFilters(r: ChatResponse): string[] {
  const parts: string[] = [];
  if (r.filters.status) parts.push(`상태: ${r.filters.status}`);
  if (r.filters.period) {
    const range = r.period_resolved ? ` (${r.period_resolved.from} ~ ${r.period_resolved.to})` : "";
    parts.push(`기간: ${PERIOD_KO[r.filters.period]}${range}`);
  }
  return parts;
}

function Answer({ response, count, restored }: { response: ChatResponse; count?: number | null; restored?: boolean }) {
  const conditions = describeFilters(response);
  // 가드레일로 막힌 답(E7): 조건·표 없이 회색 안내
  if (response.blocked) {
    return (
      <div className="chat-answer blocked">
        <p className="chat-text">{response.answer}</p>
        <p className="chat-blocked-reason">안내 · {response.blocked}</p>
      </div>
    );
  }
  const total = restored ? count : response.rows.length;
  return (
    <div className="chat-answer">
      <p className="chat-text">{response.answer}</p>
      <ul className="chat-conds" aria-label="조회 조건">
        {conditions.length === 0 ? (
          <li className="tag">조건 없음</li>
        ) : (
          conditions.map((c) => (
            <li key={c} className="tag">
              {c}
            </li>
          ))
        )}
        {total !== null && total !== undefined && <li className="tag dark">{total}건</li>}
      </ul>
      {restored && !!total && <p className="hint chat-restored">지난 대화라 결과 표는 없습니다. 다시 물으면 표가 보입니다.</p>}
      {response.rows.length > 0 && (
        // 모바일에서는 줄마다 카드, 태블릿·PC 에서는 표 (styles.css table.cards)
        <table className="cells cards">
          <thead>
            <tr>
              <th>B/L 번호</th>
              <th>수하인</th>
              <th>품명</th>
              <th>입항일</th>
              <th>통관 상태</th>
              <th>마지막 변경</th>
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            {response.rows.map((s) => (
              <tr key={s.bl_no}>
                <td data-label="B/L 번호">
                  <strong>{s.bl_no}</strong>
                </td>
                <td data-label="수하인">{s.consignee}</td>
                <td data-label="품명">{s.item}</td>
                <td data-label="입항일">{s.arrived_at}</td>
                <td data-label="통관 상태">{s.customs_status}</td>
                <td data-label="마지막 변경">{s.last_event_at}</td>
                <td data-label="작업">
                  {s.job_id ? (
                    <button type="button" className="link" onClick={() => navigate(`/jobs/${encodeURIComponent(s.job_id!)}`)}>
                      {s.job_id}
                    </button>
                  ) : (
                    <span className="hint">-</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** ask: 대시보드 화물 통계를 누르면 주소(#/chat?q=…)로 오는 질문. 열릴 때 한 번 보낸다 (G15). */
export function ChatPage({ ask: askOnOpen }: { ask?: string } = {}) {
  const [messages, setMessages] = useState<ChatMessage[]>(loadMessages);
  const [sessionId, setSessionId] = useState(chatSessionId);
  const asked = useRef(false);
  // 이 화면에서 질문을 보냈으면 늦게 온 서버 기록으로 덮지 않는다
  const touched = useRef(false);
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const mutation = useMutation({
    mutationFn: (message: string) => sendChat({ session_id: sessionId, message }),
    onSuccess: (response) => setMessages((m) => [...m, { role: "assistant", response }]),
  });
  const history = useQuery({
    queryKey: ["chat-history", sessionId],
    queryFn: () => getChatHistory(sessionId),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (history.data && !touched.current) setMessages(historyToMessages(history.data.messages));
  }, [history.data]);

  function newChat() {
    const id = newSessionId();
    sessionStorage.setItem(SESSION_KEY, id);
    touched.current = false;
    mutation.reset();
    setMessages([]);
    setSessionId(id);
  }

  useEffect(() => {
    sessionStorage.setItem(MESSAGES_KEY, JSON.stringify(messages));
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages, mutation.isPending]);

  function ask(raw: string) {
    const text = raw.trim();
    if (!text || mutation.isPending) return;
    touched.current = true;
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    mutation.mutate(text);
  }

  useEffect(() => {
    if (!askOnOpen || asked.current) return;
    asked.current = true;
    // 새로 고쳐도 다시 보내지 않게 주소에서 질문을 뺀다 (hashchange 를 내지 않는 replaceState)
    window.history.replaceState(null, "", "#/chat");
    ask(askOnOpen.slice(0, MAX_MESSAGE));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 열릴 때 한 번만
  }, []);

  return (
    <section className={messages.length > 0 ? "chat has-log" : "chat"}>
      <div className="chat-head">
        <h1 className="chat-title">AI chat</h1>
        {messages.length > 0 && (
          <button type="button" className="chat-new" disabled={mutation.isPending} onClick={newChat}>
            <Icon name="plus" size={18} />
            새 대화
          </button>
        )}
      </div>

      <div className="chat-examples">
        <h2>무엇을 찾을까요?</h2>
        <p>화물 현황을 물어보면 조회 조건과 결과를 함께 보여 줍니다</p>
        <ul className="example-list" aria-label="예시 질문">
          {EXAMPLES.map((q) => (
            <li key={q}>
              <button type="button" className="example" disabled={mutation.isPending} onClick={() => ask(q)}>
                {q}
                <Icon name="chevron" size={20} />
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="chat-main">
        <div className="chat-log" aria-label="대화" role="log">
          {messages.length === 0 && <p className="empty chat-empty">아직 대화가 없습니다. 예시를 누르거나 질문을 입력하세요.</p>}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <p key={i} className="chat-user chat-text">
                {m.text}
              </p>
            ) : (
              <Answer key={i} response={m.response} count={m.count} restored={m.restored} />
            ),
          )}
          {history.isLoading && messages.length === 0 && (
            <p className="chat-pending" role="status">
              지난 대화를 불러오는 중
            </p>
          )}
          {history.error && !noHistoryRoute(history.error) && (
            <p className="hint" role="status">
              지난 대화를 불러오지 못해 이 화면에서 나눈 대화만 보입니다.
            </p>
          )}
          {mutation.isPending && (
            <p className="chat-pending" role="status">
              답을 찾는 중
            </p>
          )}
          {mutation.error && (
            <p className="error" role="alert">
              {mutation.error.message}
            </p>
          )}
          <div ref={endRef} />
        </div>

        <form
          className="chat-form"
          onSubmit={(e) => {
            e.preventDefault();
            ask(input);
          }}
        >
          <input
            type="text"
            aria-label="질문"
            placeholder="질문을 입력하세요"
            value={input}
            maxLength={MAX_MESSAGE}
            onChange={(e) => setInput(e.target.value)}
          />
          <button type="submit" className="send" aria-label="보내기" disabled={!input.trim() || mutation.isPending}>
            <Icon name="arrow-up" />
          </button>
        </form>
      </div>
    </section>
  );
}
