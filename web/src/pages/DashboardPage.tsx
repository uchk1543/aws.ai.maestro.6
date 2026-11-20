// G15 대시보드: 지금 할 일 · 통관 흐름 · 서류 처리 (GET /api/stats, F11 #195).
// 숫자는 서버가 센 값 그대로 쓴다. 화면은 다시 세지 않는다(비율만 그린다). 통계를 누르면 연관된 문서 분류 내역(서류)이나
// AI chat 질문(화물)으로 간다. 오른쪽 위 ON/OFF: ON은 부산항 장면(Blender 렌더) 위에 통계가 컨테이너처럼 올라오고 숫자가 차오른다.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { getStats } from "../api";
import { Icon } from "../components/Icon";
import { navigate } from "../route";
import { DOC_TYPES, type StatsResponse } from "../types";
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
  go: () => void;
}

function todosOf(s: StatsResponse): Todo[] {
  const t = s.todo;
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
    { key: "delayed", label: "통관 지연 화물", hint: s.delay_rule, value: t.delayed, go: () => navigate("/chat", { q: "지금 통관이 늦어지고 있는 화물 전부 보여줘" }) },
  ];
}

function TodoTile({ todo, fx, order }: { todo: Todo; fx: boolean; order: number }) {
  const shown = useCountUp(todo.value, fx, 350 + order * 120);
  return (
    <li className="todo-tile-wrap" style={{ "--i": order } as CSSProperties}>
      <button type="button" className={todo.alert ? "todo-tile alert" : "todo-tile"} onClick={todo.go} aria-label={`${todo.label} ${todo.value}건 보기`}>
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

/**
 * 인트로 영상에서 통관 단계가 시작하는 때(초). 영상은 컨테이너 하나를 따라간다:
 * 배 입항 → 안벽 크레인 하역 → 트럭으로 장치장 사이 이동 → 검사대 → 게이트 반출 → 항구 전체로 빠짐.
 * 영상을 다시 렌더하면 이 시간도 함께 고친다 (AWS_개인/video/blender/dash_port/build_scene.py 의 프레임 ÷ 24).
 */
export const STAGE_TIMES: { status: string; from: number }[] = [
  { status: "입항", from: 0 },
  { status: "수입신고", from: 4 },
  { status: "심사 중", from: 11 },
  { status: "검사 중", from: 15.5 },
  { status: "수리", from: 17 },
  { status: "반출", from: 18.5 },
];

/** 영상 t초에 보이는 단계 번호. */
export function stageAt(t: number): number {
  let at = 0;
  STAGE_TIMES.forEach((s, i) => {
    if (t >= s.from) at = i;
  });
  return at;
}

/** 부산항 장면: 컨테이너 하나가 입항부터 반출까지 가는 인트로를 한 번, 그다음 항구 전체 항공샷을 되풀이한다. */
function PortHero({ stats }: { stats: StatsResponse | undefined }) {
  const [phase, setPhase] = useState<"intro" | "loop">("intro");
  const [stage, setStage] = useState(0);
  const loopRef = useRef<HTMLVideoElement>(null);
  const total = stats ? stats.todo.waiting_approval + stats.todo.unclassified + stats.todo.delayed : null;
  const countOf = (status: string) => stats?.flow.find((f) => f.status === status)?.count;

  function toLoop() {
    setPhase("loop");
    void loopRef.current?.play?.()?.catch?.(() => undefined);
  }

  function stageClass(i: number): string {
    if (phase === "loop" || i < stage) return "done";
    return i === stage ? "now" : "";
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
        onTimeUpdate={(e) => setStage(stageAt(e.currentTarget.currentTime))}
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
        preload="auto"
        aria-hidden="true"
      />
      <div className="port-shade" />
      <div className="port-copy">
        <p className="port-date">{stats ? stats.today : " "}</p>
        <p className="port-title">부산항 통관 현황</p>
        <p className="port-sub">{total === null ? "불러오는 중" : `확인할 일 ${total}건이 들어와 있습니다`}</p>
      </div>
      {/* 영상 속 컨테이너가 지금 지나는 통관 단계. 숫자는 그 단계의 화물 수(서버 값) */}
      <ol className="port-stages" aria-label="영상 속 통관 단계">
        {STAGE_TIMES.map((s, i) => (
          <li key={s.status} className={stageClass(i)} aria-current={stageClass(i) === "now" ? "step" : undefined}>
            <span className="port-stage-dot" aria-hidden="true" />
            <span className="port-stage-name">{s.status}</span>
            {countOf(s.status) !== undefined && <b className="port-stage-count">{countOf(s.status)}</b>}
          </li>
        ))}
      </ol>
    </div>
  );
}

function FlowPanel({ stats, fx }: { stats: StatsResponse; fx: boolean }) {
  const max = Math.max(1, ...stats.flow.map((f) => f.count));
  return (
    <section className="dash-panel" aria-labelledby="flow-title">
      <h2 id="flow-title">통관 흐름</h2>
      <p className="hint dash-note">단계를 누르면 그 화물을 AI chat으로 찾아봅니다</p>
      <ol className="flow">
        {stats.flow.map((f, i) => (
          <li key={f.status}>
            <button
              type="button"
              className="flow-row"
              style={{ "--i": i } as CSSProperties}
              onClick={() => navigate("/chat", { q: `${f.status} 화물 전체 알려줘` })}
              aria-label={`${f.status} ${f.count}건`}
            >
              <span className="flow-name">{f.status}</span>
              <span className="flow-bar">
                <span className="flow-fill" style={{ width: `${(f.count / max) * 100}%` }} />
              </span>
              <span className="flow-count">{f.count}</span>
            </button>
          </li>
        ))}
      </ol>

      <h3 className="dash-sub">
        통관 지연 <span className="count">{stats.todo.delayed}건</span>
      </h3>
      <p className="hint dash-note">{stats.delay_rule}</p>
      {stats.delayed.length === 0 ? (
        <p className="empty">지연된 화물이 없습니다.</p>
      ) : (
        <ul className="delayed">
          {stats.delayed.map((d) => (
            <li key={d.bl_no} className="delayed-row">
              <div className="delayed-main">
                <strong>{d.bl_no}</strong>
                <span className="hint">
                  {d.consignee} · {d.item}
                </span>
              </div>
              <span className="tag">{d.customs_status}</span>
              <span className={fx ? "delayed-days pulse" : "delayed-days"}>{d.days}일째</span>
              {d.job_id && (
                <button type="button" className="link" onClick={() => navigate(`/jobs/${encodeURIComponent(d.job_id!)}`)}>
                  작업
                </button>
              )}
            </li>
          ))}
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

function DocsPanel({ stats, fx }: { stats: StatsResponse; fx: boolean }) {
  const max = Math.max(1, ...DOC_TYPES.map((t) => stats.docs_by_type[t] ?? 0));
  return (
    <section className="dash-panel" aria-labelledby="docs-title">
      <h2 id="docs-title">서류 처리</h2>
      <p className="hint dash-note">누르면 그 서류를 문서 분류 내역에서 봅니다</p>

      <button type="button" className="auto-box" onClick={() => navigate("/documents", { job_status: "done" })}>
        <AutoRing auto={stats.auto.auto} finished={stats.auto.finished} fx={fx} />
        <span className="auto-text">
          <strong>자동 처리율</strong>
          <span className="hint">
            끝난 작업 {stats.auto.finished}건 중 {stats.auto.auto}건이 사람 손 없이 WMS에 등록됐습니다
          </span>
          {/* 목록(job_status=done)에는 사람이 승인해 끝난 작업도 들어가 숫자와 다를 수 있다 (#201 리뷰) */}
          <span className="hint auto-link-note">누르면 처리가 끝난 작업의 서류를 봅니다 (사람이 승인한 작업 포함)</span>
        </span>
      </button>

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

      <h3 className="dash-sub">자주 걸린 오류</h3>
      {stats.top_rules.length === 0 ? (
        <p className="empty">걸린 오류가 없습니다.</p>
      ) : (
        <ol className="rules">
          {stats.top_rules.map((r) => (
            <li key={r.rule_id}>
              <button type="button" className="rule-row" onClick={() => navigate("/documents", { rule_id: r.rule_id })}>
                <span className={r.grade === "불일치" ? "grade grade-mismatch" : r.grade === "참고" ? "grade grade-note" : "grade"}>{r.grade}</span>
                <span className="rule-main">
                  <code>{r.rule_id}</code>
                  <span className="hint">{r.example}</span>
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

export function DashboardPage() {
  const [fx, setFx] = useState(initialFx);
  const query = useQuery({ queryKey: ["stats"], queryFn: getStats, refetchInterval: STATS_REFRESH_MS });
  const stats = query.data;

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
            {todosOf(stats).map((todo, i) => (
              <TodoTile key={todo.key} todo={todo} fx={fx} order={i} />
            ))}
          </ul>
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
