// G8 현황 채팅: POST /api/chat. 답마다 답 문장·조회 조건·결과 표를 보여 준다.
// 조회·집계·기간 계산은 서버 코드가 한다. 화면은 받은 값을 그대로 보여 준다 (agent-design.md 9번).
import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { sendChat } from "../api";
import { navigate } from "../route";
import type { ChatResponse, Period } from "../types";

const SESSION_KEY = "team06-chat-session";
const MESSAGES_KEY = "team06-chat-messages";
export const MAX_MESSAGE = 500;

const PERIOD_KO: Record<Period, string> = {
  today: "오늘",
  this_week: "이번 주",
  last_week: "지난주",
  range: "기간 지정",
};

export type ChatMessage = { role: "user"; text: string } | { role: "assistant"; response: ChatResponse };

/** 탭마다 대화 하나. 새로 고쳐도 같은 session_id 를 쓴다. */
export function chatSessionId(): string {
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id = typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `s-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
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

function Answer({ response }: { response: ChatResponse }) {
  const conditions = describeFilters(response);
  return (
    <div className="chat-answer">
      <p className="chat-text">{response.answer}</p>
      <p className="chat-conditions">
        조회 조건: {conditions.length > 0 ? conditions.join(" · ") : "없음"} · {response.rows.length}건
      </p>
      {response.rows.length > 0 && (
        <div className="table-scroll">
          <table className="cells">
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
                  <td>{s.bl_no}</td>
                  <td>{s.consignee}</td>
                  <td>{s.item}</td>
                  <td>{s.arrived_at}</td>
                  <td>{s.customs_status}</td>
                  <td>{s.last_event_at}</td>
                  <td>
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
        </div>
      )}
    </div>
  );
}

export function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>(loadMessages);
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const mutation = useMutation({
    mutationFn: (message: string) => sendChat({ session_id: chatSessionId(), message }),
    onSuccess: (response) => setMessages((m) => [...m, { role: "assistant", response }]),
  });

  useEffect(() => {
    sessionStorage.setItem(MESSAGES_KEY, JSON.stringify(messages));
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages, mutation.isPending]);

  function send() {
    const text = input.trim();
    if (!text || mutation.isPending) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    mutation.mutate(text);
  }

  return (
    <section className="chat">
      <h1>AI chat</h1>
      <p className="hint">화물 현황을 물어보세요. 예: 이번 주 통관 지연 건은?</p>

      <div className="panel chat-log" aria-label="대화" role="log">
        {messages.length === 0 && <p className="empty">아직 대화가 없습니다.</p>}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="chat-user">
              <p className="chat-text">{m.text}</p>
            </div>
          ) : (
            <Answer key={i} response={m.response} />
          ),
        )}
        {mutation.isPending && <p className="hint">답을 찾는 중…</p>}
        {mutation.error && (
          <p className="error" role="alert">
            {mutation.error.message}
          </p>
        )}
        <div ref={endRef} />
      </div>

      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          send();
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
        <button type="submit" className="primary" disabled={!input.trim() || mutation.isPending}>
          보내기
        </button>
      </form>
    </section>
  );
}
