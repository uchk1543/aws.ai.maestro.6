// G10·G11 문서 분류 내역: 서류 종류를 고르면 그 종류로 분류된 서류를 카드로 한 장씩 보여 준다 (GET /api/documents, 서버 약속은 제안 중).
// 카드: 왼쪽 서류 원본 | 오른쪽 인식 결과. 좌우로 밀거나 이전·다음 버튼(또는 ←·→ 키)으로 넘긴다.
// 종류별 건수(counts)와 분류 근거(reason)는 서버가 준 값을 그대로 쓴다. 화면은 다시 세거나 분류하지 않는다.
// 대시보드 통계에서 들어오면 주소의 거르기(#/documents?grade=불일치 등, F11)를 칩으로 보여 주고 X로 지운다.
import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ApiError, getDocuments } from "../api";
import { DocCard } from "../components/DocCard";
import { Icon } from "../components/Icon";
import { navigate } from "../route";
import { DOC_TYPE_KO, DOC_TYPES, type DocType, type DocumentFilters, type DocumentsResponse, type Grade, type JobStatus } from "../types";
import { STATUS_KO } from "./JobPage";

/** 종류 이름. unknown(분류 실패 포함)은 "분류 못 함"으로 모은다. */
export const KIND_LABEL: Record<DocType, string> = { ...DOC_TYPE_KO, unknown: "분류 못 함" };

const JOB_STATUSES: JobStatus[] = ["queued", "running", "waiting_approval", "done", "failed"];
const GRADES: Grade[] = ["불일치", "확인 필요", "참고"];

/** 주소 조건 → 서버 거르기. 값 목록 밖의 값은 버린다. */
export function filtersOf(params: Record<string, string>): DocumentFilters {
  const f: DocumentFilters = {};
  if (JOB_STATUSES.includes(params.job_status as JobStatus)) f.job_status = params.job_status as JobStatus;
  if (GRADES.includes(params.grade as Grade)) f.grade = params.grade as Grade;
  if (params.rule_id && /^[A-Za-z0-9_-]{1,40}$/.test(params.rule_id)) f.rule_id = params.rule_id;
  if (params.hs === "pending") f.hs = "pending";
  return f;
}

/** 거르기 칩 글자 */
function filterLabels(f: DocumentFilters): string[] {
  const out: string[] = [];
  if (f.job_status) out.push(`작업 ${STATUS_KO[f.job_status]}`);
  if (f.grade) out.push(`${f.grade}가 남은 작업`);
  if (f.rule_id) out.push(`규칙 ${f.rule_id}`);
  if (f.hs) out.push("HS 고를 품목이 있는 작업");
  return out;
}

export function DocHistoryPage({ params = {} }: { params?: Record<string, string> }) {
  const filters = filtersOf(params);
  const filtered = Object.keys(filters).length > 0;
  const startType = DOC_TYPES.includes(params.type as DocType) ? (params.type as DocType) : "commercial_invoice";
  // 주소로 종류를 정했거나 거르기가 없으면 처음 종류를 그대로 둔다. 거르기만 있으면 서류가 있는 첫 종류로 옮긴다
  const autoPick = useRef(filtered && !params.type);
  const [docType, setDocType] = useState<DocType>(startType);
  const [index, setIndex] = useState(0);
  const trackRef = useRef<HTMLDivElement>(null);
  // 버튼·키로 넘길 때 가는 카드. 스크롤이 거기 닿을 때까지는 스크롤 위치로 지금 카드를 바꾸지 않는다
  const targetRef = useRef<number | null>(null);
  const query = useInfiniteQuery({
    queryKey: ["documents", docType, filters],
    queryFn: ({ pageParam }) => getDocuments(docType, pageParam, filters),
    initialPageParam: null as string | null,
    getNextPageParam: (last: DocumentsResponse) => last.next_cursor,
  });

  const pages = query.data?.pages ?? [];
  const counts = pages[0]?.counts;
  const items = pages.flatMap((p) => p.items);
  const total = counts?.[docType] ?? items.length;
  const notReady = query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 501);
  const current = Math.min(index, Math.max(items.length - 1, 0));
  const hasNext = current < items.length - 1 || query.hasNextPage;

  useEffect(() => {
    if (!autoPick.current || !counts) return;
    autoPick.current = false;
    if ((counts[docType] ?? 0) > 0) return;
    const first = DOC_TYPES.find((t) => (counts[t] ?? 0) > 0);
    if (first) setDocType(first);
  }, [counts, docType]);

  function pickType(t: DocType) {
    setDocType(t);
    setIndex(0);
    trackRef.current?.scrollTo?.({ left: 0 });
  }

  /** i 번째 카드로 간다. 마지막 카드에서 다음 쪽이 있으면 먼저 불러온다. */
  async function go(i: number) {
    if (i < 0) return;
    if (i >= items.length) {
      if (!query.hasNextPage || query.isFetchingNextPage) return;
      await query.fetchNextPage();
    }
    setIndex(i);
    const track = trackRef.current;
    if (!track?.scrollTo) return;
    targetRef.current = i;
    // 부드럽게 넘기면 옆 카드의 그림이 불러와지며 칸 크기가 바뀔 때 브라우저가 앞 카드로 다시 붙여 버린다. 바로 옮긴다
    track.scrollTo({ left: i * track.clientWidth });
  }

  // 손가락으로 밀어 넘기면 스크롤 위치로 지금 카드를 정한다
  function onScroll() {
    const track = trackRef.current;
    if (!track || track.clientWidth === 0) return;
    const i = Math.round(track.scrollLeft / track.clientWidth);
    if (targetRef.current !== null) {
      if (Math.abs(track.scrollLeft - targetRef.current * track.clientWidth) > 2) return;
      targetRef.current = null;
    }
    if (i !== current && i >= 0 && i < items.length) setIndex(i);
    if (i === items.length - 1 && query.hasNextPage && !query.isFetchingNextPage) void query.fetchNextPage();
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      void go(current + 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      void go(current - 1);
    }
  }

  return (
    <section className="dochist">
      <div className="dochist-side">
        <h1>문서 분류 내역</h1>
        <p className="lead">올라온 서류를 종류별로 모아 봅니다. 종류와 근거는 AI 분류 결과입니다.</p>
        <ul className="kind-list" aria-label="서류 종류">
          {DOC_TYPES.map((t) => (
            <li key={t}>
              <button
                type="button"
                className={t === docType ? "kind active" : "kind"}
                aria-pressed={t === docType}
                onClick={() => pickType(t)}
              >
                <span>{KIND_LABEL[t]}</span>
                <span className="kind-count">{counts ? `${counts[t] ?? 0}건` : ""}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="dochist-main">
        {filtered && (
          <div className="filter-chips" aria-label="거르기">
            {filterLabels(filters).map((label) => (
              <span key={label} className="filter-chip">
                {label}
              </span>
            ))}
            <button type="button" className="filter-clear" onClick={() => navigate("/documents", { type: docType })}>
              <Icon name="close" size={16} />
              거르기 지우기
            </button>
          </div>
        )}
        <div className="deck-head">
          <h2>
            {KIND_LABEL[docType]}
            {counts && <span className="count"> {counts[docType] ?? 0}건</span>}
          </h2>
          {items.length > 0 && (
            <div className="deck-nav">
              <button type="button" className="deck-btn prev" aria-label="이전 서류" disabled={current === 0} onClick={() => void go(current - 1)}>
                <Icon name="chevron" />
              </button>
              <span className="deck-count" aria-live="polite">
                {current + 1} / {total}
              </span>
              <button
                type="button"
                className="deck-btn"
                aria-label="다음 서류"
                disabled={!hasNext || query.isFetchingNextPage}
                onClick={() => void go(current + 1)}
              >
                <Icon name="chevron" />
              </button>
            </div>
          )}
        </div>
        {docType === "unknown" && (
          <p className="hint dochist-note">종류를 정하지 못했거나 분류에 실패한 서류입니다. 작업 화면에서 확인해 주세요.</p>
        )}

        {query.isPending && (
          <p className="hint" role="status">
            불러오는 중…
          </p>
        )}
        {query.error && (
          <p className="error" role="alert">
            {query.error.message}
            {notReady && <span className="hint"> · 서버의 문서 분류 내역 조회가 아직 준비되지 않았습니다.</span>}
          </p>
        )}
        {query.isSuccess && items.length === 0 && <p className="empty">이 종류로 분류된 서류가 없습니다.</p>}

        {items.length > 0 && (
          <div
            ref={trackRef}
            className="deck"
            role="region"
            aria-roledescription="carousel"
            aria-label={`${KIND_LABEL[docType]} 서류`}
            tabIndex={0}
            onScroll={onScroll}
            // 손으로 밀기 시작하면 버튼으로 가던 목표는 버린다
            onPointerDown={() => (targetRef.current = null)}
            onWheel={() => (targetRef.current = null)}
            onKeyDown={onKeyDown}
          >
            {items.map((d, i) => (
              <div
                key={`${d.job_id}-${d.key}-${i}`}
                className="deck-slide"
                role="group"
                aria-roledescription="slide"
                aria-label={`${i + 1} / ${total}`}
                aria-hidden={i !== current}
                inert={i !== current ? true : undefined}
              >
                <DocCard
                  record={d}
                  kindLabel={KIND_LABEL[d.doc_type]}
                  statusLabel={STATUS_KO[d.job_status]}
                  load={Math.abs(i - current) <= 1}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
