// G15 대시보드: 지금 할 일 · 통관 흐름 · 서류 처리 (GET /api/stats, F11 #195).
// 숫자는 서버가 센 값 그대로 쓴다. 화면은 다시 세지 않는다(비율만 그린다).
// #252: 할 일 타일은 '작업' 하나에 다음 할 일 하나(next_action)로 센다. 카드를 누르면 그 자리에 작업 목록이 펼쳐지고
//       줄을 누르면 작업 화면으로 간다. 서버가 새 칸·작업 목록을 아직 주지 않으면 옛 타일과 문서 분류 내역 이동을 쓴다.
//       AI chat 에 질문을 자동으로 보내는 클릭은 없다. 오른쪽 위 ON/OFF: ON은 부산항 장면(Blender 렌더).
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { ApiError, getJobs, getStats } from "../api";
import { Icon } from "../components/Icon";
import { navigate } from "../route";
import { shortRuleName } from "../ruleNames";
import { DOC_TYPES, type StatsResponse, type TodoKind } from "../types";
import { KIND_LABEL } from "./DocHistoryPage";

export const FX_KEY = "team06-dashboard-fx";
const STATS_REFRESH_MS = 60_000;
const BASE = import.meta.env.BASE_URL;

/** 처음 보기: 움직임 줄이기 설정이면 OFF, 아니면 지난번 고른 값(없으면 ON). */
export function initialFx(): boolean {
  try {
    if (typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
    return window.localStorage.getItem(FX_KEY) !== "off";
  } catch {
    return true;
  }
}

/** 0 에서 target 까지 숫자가 차오른다 (ON 일 때만). */
function useCountUp(target: number, run: boolean, delay = 0): number {
  const [value, setValue] = useState(run ? 0 : target);
  useEffect(() => {
    if (!run || typeof window.requestAnimationFrame !== "function") {
      setValue(target);
      return;
    }
    let frame = 0;
    const start = performance.now() + delay;
    const tick = (now: number) => {
      const t = Math.min(1, Math.max(0, (now - start) / 900));
      setValue(Math.round(target * (1 - Math.pow(1 - t, 3))));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, run, delay]);
  return value;
}

interface Todo {
  key: string;
  label: string;
  hint: string;
  value: number;
  alert?: boolean;
  /** 그 자리에 목록을 펼치는 타일이면 펼친 상태 (#252) */
  expanded?: boolean;
  go: () => void;
}

export const TODO_KINDS: TodoKind[] = ["fix_docs", "choose_hs", "approve", "reupload", "wait"];

/** 다음 할 일별 타일 (#252). 단위는 모두 '작업' */
export const KIND_TILE: Record<TodoKind, { label: string; hint: string; alert?: boolean }> = {
  fix_docs: { label: "오류 서류", hint: "불일치로 인해 서류 재업로드 필요", alert: true },
  choose_hs: { label: "HS 미작성", hint: "작업자가 HS 확인하고 전송 필요" },
  approve: { label: "미승인 서류", hint: "서류 확인 후 승인 필요" },
  reupload: { label: "미인식 서류", hint: "서류 재촬영 필요" },
  wait: { label: "처리 중", hint: "처리가 끝나지 않은 서류" },
};

/** 작업 목록 API 가 없을 때(배포 전) 대신 여는 문서 분류 내역 거르기 */
const FALLBACK: Record<TodoKind, Record<string, string>> = {
  fix_docs: { job_status: "waiting_approval", grade: "불일치" },
  choose_hs: { job_status: "waiting_approval", hs: "pending" },
  approve: { job_status: "waiting_approval" },
  reupload: { job_status: "failed" },
  wait: { job_status: "running" },
};

/** 서버가 다음 할 일별 작업 수를 주는지 (#252 PR A 뒤) */
export function hasNextCounts(s: StatsResponse): boolean {
  return typeof s.todo.fix_docs === "number";
}

/** 영상 위 "확인할 일 N건": 새 서버면 할 일 타일의 합(작업 수), 옛 서버면 예전 셈 */
export function todoTotal(s: StatsResponse): number {
  if (hasNextCounts(s)) return TODO_KINDS.reduce((n, k) => n + (s.todo[k] ?? 0), 0);
  return s.todo.waiting_approval + s.todo.unclassified + s.todo.delayed;
}

function scrollToDelayed() {
  document.getElementById("dash-delayed")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

function todosOf(s: StatsResponse, open: TodoKind | null, toggle: (k: TodoKind) => void): Todo[] {
  const t = s.todo;
  if (hasNextCounts(s)) {
    return TODO_KINDS.map((kind) => {
      const tile = KIND_TILE[kind];
      const value = t[kind] ?? 0;
      return { key: kind, label: tile.label, hint: tile.hint, value, alert: Boolean(tile.alert) && value > 0, expanded: open === kind, go: () => toggle(kind) };
    });
  }
  // 옛 서버: 예전 타일. 통관 지연은 AI chat 대신 같은 화면의 지연 목록으로 내려간다 (#252)
  return [
    { key: "approve", label: "승인 대기", hint: "작업", value: t.waiting_approval, go: () => navigate("/documents", { job_status: "waiting_approval" }) },
    {
      key: "mismatch",
      label: "불일치 남은 작업",
      hint: "서류를 고쳐 다시",
      value: t.mismatch_jobs,
      alert: t.mismatch_jobs > 0,
      go: () => navigate("/documents", { job_status: "waiting_approval", grade: "불일치" }),
    },
    { key: "hs", label: "HS 고를 품목", hint: "사람 확인 필요", value: t.hs_pending, go: () => navigate("/documents", { job_status: "waiting_approval", hs: "pending" }) },
    { key: "unknown", label: "분류 못 한 서류", hint: "종류를 정하지 못함", value: t.unclassified, go: () => navigate("/documents", { type: "unknown" }) },
    { key: "delayed", label: "통관 지연 화물", hint: s.delay_rule, value: t.delayed, go: scrollToDelayed },
  ];
}

function TodoTile({ todo, fx, order }: { todo: Todo; fx: boolean; order: number }) {
  const shown = useCountUp(todo.value, fx, 350 + order * 120);
  return (
    <li className="todo-tile-wrap" style={{ "--i": order } as CSSProperties}>
      <button
        type="button"
        className={["todo-tile", todo.alert && "alert", todo.expanded && "open"].filter(Boolean).join(" ")}
        onClick={todo.go}
        aria-label={`${todo.label} ${todo.value}건 보기`}
        aria-expanded={todo.expanded === undefined ? undefined : todo.expanded}
        aria-controls={todo.expanded ? "dash-jobs" : undefined}
      >
        <span className="todo-label">{todo.label}</span>
        <span className="todo-value">
          {shown}
          <small>건</small>
        </span>
        <span className="todo-hint">{todo.hint}</span>
      </button>
    </li>
  );
}

/** 부산항 장면: 컨테이너 하나가 입항부터 반출까지 가는 인트로를 한 번, 그다음 항구 전체 항공샷을 되풀이한다.
 * 영상 위에는 날짜·제목·확인할 일 수만 둔다. 단계별 화물 수는 아래 '통관 흐름'에 있다 (G18 #255). */
function PortHero({ stats }: { stats: StatsResponse | undefined }) {
  const [phase, setPhase] = useState<"intro" | "loop">("intro");
  const loopRef = useRef<HTMLVideoElement>(null);
  const total = stats ? todoTotal(stats) : null;

  function toLoop() {
    setPhase("loop");
    void loopRef.current?.play?.()?.catch?.(() => undefined);
  }

  return (
    <div className="port-hero">
      <img className="port-media" src={`${BASE}dashboard/port-poster.jpg`} alt="" aria-hidden="true" />
      <video
        className={phase === "intro" ? "port-media on" : "port-media"}
        src={`${BASE}dashboard/port-intro.mp4`}
        poster={`${BASE}dashboard/port-poster.jpg`}
        autoPlay
        muted
        playsInline
        preload="auto"
        onEnded={toLoop}
        onError={toLoop}
        aria-hidden="true"
        data-testid="port-intro"
      />
      <video
        ref={loopRef}
        className={phase === "loop" ? "port-media on" : "port-media"}
        src={`${BASE}dashboard/port-loop.mp4`}
        muted
        loop
        playsInline
        preload="metadata"
        aria-hidden="true"
      />
      <div className="port-shade" />
      <div className="port-copy">
        <p className="port-date">{stats ? stats.today : " "}</p>
        <p className="port-title">부산항 통관 현황</p>
        <p className="port-sub">{total === null ? "불러오는 중" : `확인할 일 ${total}건이 들어와 있습니다`}</p>
      </div>
    </div>
  );
}

/** 카드를 누르면 그 자리에 펼치는 작업 목록 (#252). 줄을 누르면 작업 화면으로 간다. */
function JobsPanel({ kind, count, onClose }: { kind: TodoKind; count: number; onClose: () => void }) {
  const query = useQuery({ queryKey: ["jobs", kind], queryFn: () => getJobs(kind), retry: false });
  const noRoute = query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 501);
  const tile = KIND_TILE[kind];
  return (
    <section id="dash-jobs" className={`dash-jobs dash-jobs-${kind}`} aria-label={`${tile.label} 작업 목록`}>
      <div className="dash-jobs-head">
        <h2>
          {tile.label} <span className="count">{count}건</span>
        </h2>
        <button type="button" className="dash-jobs-close" aria-label="목록 닫기" onClick={onClose}>
          <Icon name="close" size={18} />
        </button>
      </div>
      {query.isPending && <p className="hint">작업 목록을 불러오는 중…</p>}
      {noRoute && (
        <p className="hint">
          작업 목록을 아직 볼 수 없습니다.{" "}
          <button type="button" className="link" onClick={() => navigate("/documents", FALLBACK[kind])}>
            작업 내역에서 보기
          </button>
        </p>
      )}
      {query.error && !noRoute && (
        <p className="error" role="alert">
          {query.error.message}
        </p>
      )}
      {query.data && query.data.items.length === 0 && <p className="empty">해당하는 작업이 없습니다.</p>}
      {query.data && query.data.items.length > 0 && (
        <ul className="dash-job-list">
          {query.data.items.map((j) => (
            <li key={j.job_id}>
              <button type="button" className="dash-job" onClick={() => navigate(`/jobs/${encodeURIComponent(j.job_id)}`)}>
                <span className="dash-job-main">
                  <strong>{j.bl_no ? `B/L ${j.bl_no}` : j.job_id}</strong>
                  <span className="hint">{[j.consignee ?? "수입자 모름", j.created_at].join(" · ")}</span>
                </span>
                <span className="dash-job-next">{j.next_action.message}</span>
                <Icon name="chevron" size={18} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function FlowPanel({ stats, fx }: { stats: StatsResponse; fx: boolean }) {
  const max = Math.max(1, ...stats.flow.map((f) => f.count));
  return (
    <section className="dash-panel" aria-labelledby="flow-title">
      <h2 id="flow-title">통관 흐름</h2>
      <p className="hint dash-note">통관 단계별 화물 수 · 화물을 찾으려면 AI chat에 물어보세요</p>
      <ol className="flow">
        {stats.flow.map((f, i) => (
          <li key={f.status} className="flow-row static" style={{ "--i": i } as CSSProperties} aria-label={`${f.status} ${f.count}건`}>
            <span className="flow-name">{f.status}</span>
            <span className="flow-bar">
              <span className="flow-fill" style={{ width: `${(f.count / max) * 100}%` }} />
            </span>
            <span className="flow-count">{f.count}</span>
          </li>
        ))}
      </ol>

      <h3 className="dash-sub" id="dash-delayed">
        통관 지연 <span className="count">{stats.todo.delayed}건</span>
      </h3>
      <p className="hint dash-note">{stats.delay_rule}</p>
      {stats.delayed.length === 0 ? (
        <p className="empty">지연된 화물이 없습니다.</p>
      ) : (
        <ul className="delayed">
          {stats.delayed.map((d) => {
            const body = (
              <>
                <span className="delayed-main">
                  <strong>{d.bl_no}</strong>
                  <span className="hint">
                    {d.consignee} · {d.item}
                  </span>
                </span>
                <span className="tag">{d.customs_status}</span>
                <span className={fx ? "delayed-days pulse" : "delayed-days"}>{d.days}일째</span>
              </>
            );
            // 화물 기록에 작업이 있으면 줄 전체가 그 작업 화면으로 간다 (G18 #255). 미리 넣은 가상 기록은 작업이 없다
            return (
              <li key={d.bl_no}>
                {d.job_id ? (
                  <button
                    type="button"
                    className="delayed-row go"
                    onClick={() => navigate(`/jobs/${encodeURIComponent(d.job_id!)}`)}
                    aria-label={`${d.bl_no} 작업 화면 열기`}
                  >
                    {body}
                    <Icon name="chevron" size={18} />
                  </button>
                ) : (
                  <div className="delayed-row" title="연결된 작업이 없는 화물 기록">
                    {body}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function AutoRing({ auto, finished, fx }: { auto: number; finished: number; fx: boolean }) {
  const rate = finished > 0 ? auto / finished : 0;
  const shown = useCountUp(Math.round(rate * 100), fx, 600);
  const r = 42;
  const len = 2 * Math.PI * r;
  return (
    <svg className="ring" viewBox="0 0 100 100" aria-hidden="true">
      <circle cx="50" cy="50" r={r} className="ring-back" />
      <circle cx="50" cy="50" r={r} className="ring-fill" strokeDasharray={len} style={{ "--len": len, "--off": len * (1 - rate) } as CSSProperties} />
      <text x="50" y="56" textAnchor="middle" className="ring-text">
        {shown}%
      </text>
    </svg>
  );
}

const AUTO_RULE = "불일치·확인 필요가 없고 모든 품목의 HS가 정해진 작업만 사람 손 없이 WMS에 등록합니다";

function DocsPanel({ stats, fx }: { stats: StatsResponse; fx: boolean }) {
  const max = Math.max(1, ...DOC_TYPES.map((t) => stats.docs_by_type[t] ?? 0));
  // '참고'는 할 일이 아니라 뺀다 (옛 서버는 섞어서 준다, #252)
  const rules = stats.top_rules.filter((r) => r.grade !== "참고");
  return (
    <section className="dash-panel" aria-labelledby="docs-title">
      <h2 id="docs-title">서류 처리</h2>
      <p className="hint dash-note">종류·오류를 누르면 그 작업들을 작업 내역에서 봅니다</p>

      <h3 className="dash-sub">종류별 서류</h3>
      <ul className="kinds">
        {DOC_TYPES.map((t, i) => (
          <li key={t}>
            <button
              type="button"
              className={t === "unknown" ? "flow-row kind-row unknown" : "flow-row kind-row"}
              style={{ "--i": i } as CSSProperties}
              onClick={() => navigate("/documents", { type: t })}
              aria-label={`${KIND_LABEL[t]} ${stats.docs_by_type[t] ?? 0}장`}
            >
              <span className="flow-name">{KIND_LABEL[t]}</span>
              <span className="flow-bar">
                <span className="flow-fill" style={{ width: `${((stats.docs_by_type[t] ?? 0) / max) * 100}%` }} />
              </span>
              <span className="flow-count">{stats.docs_by_type[t] ?? 0}</span>
            </button>
          </li>
        ))}
      </ul>

      <h3 className="dash-sub">자동 처리율</h3>
      <div className="auto-box">
        <AutoRing auto={stats.auto.auto} finished={stats.auto.finished} fx={fx} />
        <span className="auto-text">
          <span className="hint">
            처리를 마친 작업 {stats.auto.finished}건(승인 대기 포함) 중 {stats.auto.auto}건이 사람 손 없이 WMS에 등록됐습니다
          </span>
          <span className="hint auto-link-note">{stats.auto.rule || AUTO_RULE}</span>
        </span>
      </div>

      <h3 className="dash-sub">자주 걸린 오류</h3>
      {rules.length === 0 ? (
        <p className="empty">걸린 오류가 없습니다.</p>
      ) : (
        <ol className="rules">
          {rules.map((r) => (
            <li key={r.rule_id}>
              <button type="button" className="rule-row" onClick={() => navigate("/documents", { rule_id: r.rule_id })}>
                <span className={r.grade === "불일치" ? "grade grade-mismatch" : "grade"}>{r.grade}</span>
                <span className="rule-main">
                  <strong className="rule-name">{shortRuleName(r.rule_id, r.grade, r.name, r.example)}</strong>
                  <span className="hint">
                    {r.example} · <code>{r.rule_id}</code>
                  </span>
                </span>
                <span className="rule-count">{r.count}건</span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/** open: 주소(#/dashboard?open=…)로 온 펼친 카드. 작업 화면에서 뒤로 오면 같은 목록이 펼쳐져 있다 (#252) */
export function DashboardPage({ open: openParam }: { open?: string } = {}) {
  const [fx, setFx] = useState(initialFx);
  const [open, setOpen] = useState<TodoKind | null>(() =>
    TODO_KINDS.includes(openParam as TodoKind) ? (openParam as TodoKind) : null,
  );
  const query = useQuery({ queryKey: ["stats"], queryFn: getStats, refetchInterval: STATS_REFRESH_MS });
  const stats = query.data;

  function toggleOpen(kind: TodoKind) {
    const next = open === kind ? null : kind;
    setOpen(next);
    // 새 기록을 쌓지 않고 주소만 바꾼다 (뒤로 가기가 대시보드 안을 돌지 않게)
    window.history.replaceState(null, "", next ? `#/dashboard?open=${next}` : "#/dashboard");
  }

  function toggle() {
    setFx((on) => {
      try {
        window.localStorage.setItem(FX_KEY, on ? "off" : "on");
      } catch {
        // 저장이 막힌 브라우저에서도 전환은 된다
      }
      return !on;
    });
  }

  return (
    <section className={fx ? "dash fx" : "dash"}>
      <div className="dash-top">
        <h1>대시보드</h1>
        <button type="button" className={fx ? "fx-toggle on" : "fx-toggle"} aria-pressed={fx} onClick={toggle}>
          <span className="fx-knob" aria-hidden="true" />
          애니메이션 {fx ? "ON" : "OFF"}
        </button>
      </div>

      {fx && <PortHero stats={stats} />}

      {query.isPending && (
        <p className="hint" role="status">
          통계를 불러오는 중…
        </p>
      )}
      {query.error && (
        <p className="error" role="alert">
          {query.error.message}
        </p>
      )}

      {stats && (
        <>
          <h2 className="visually-hidden">지금 할 일</h2>
          <ul className="todo-tiles" aria-label="지금 할 일">
            {todosOf(stats, open, toggleOpen).map((todo, i) => (
              <TodoTile key={todo.key} todo={todo} fx={fx} order={i} />
            ))}
          </ul>
          {open && hasNextCounts(stats) && (
            <JobsPanel kind={open} count={stats.todo[open] ?? 0} onClose={() => toggleOpen(open)} />
          )}
          <div className="dash-grid">
            <FlowPanel stats={stats} fx={fx} />
            <DocsPanel stats={stats} fx={fx} />
          </div>
          <p className="hint dash-foot">
            <Icon name="chart" size={16} /> 숫자는 서버가 센 값입니다 (1분마다 새로 고침)
          </p>
        </>
      )}
    </section>
  );
}
