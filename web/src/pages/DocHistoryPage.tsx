// G10 문서 분류 내역: 서류 종류를 고르면 그 종류로 분류된 서류 목록 (GET /api/documents, 서버 약속은 제안 중).
// 종류별 건수(counts)와 분류 근거(reason)는 서버가 준 값을 그대로 쓴다. 화면은 다시 세거나 분류하지 않는다.
// 모바일·태블릿: 위 종류 칩 + 서류 카드. PC: 왼쪽 종류 목록 | 오른쪽 표. 파일 이름을 누르면 서류 보기 창(G11).
import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, getDocuments } from "../api";
import { DocDetail } from "../components/DocDetail";
import { navigate } from "../route";
import { DOC_TYPE_KO, DOC_TYPES, type ClassifiedBy, type DocType, type DocumentRecord, type DocumentsResponse } from "../types";
import { STATUS_KO } from "./JobPage";

/** 종류 이름. unknown(분류 실패 포함)은 "분류 못 함"으로 모은다. */
export const KIND_LABEL: Record<DocType, string> = { ...DOC_TYPE_KO, unknown: "분류 못 함" };

const BY_KO: Record<ClassifiedBy, string> = { model: "자동", user: "사용자 선택" };

export function DocHistoryPage() {
  const [docType, setDocType] = useState<DocType>("commercial_invoice");
  const [opened, setOpened] = useState<DocumentRecord | null>(null);
  const query = useInfiniteQuery({
    queryKey: ["documents", docType],
    queryFn: ({ pageParam }) => getDocuments(docType, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last: DocumentsResponse) => last.next_cursor,
  });

  const pages = query.data?.pages ?? [];
  const counts = pages[0]?.counts;
  const items = pages.flatMap((p) => p.items);
  const notReady = query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 501);

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
                onClick={() => setDocType(t)}
              >
                <span>{KIND_LABEL[t]}</span>
                <span className="kind-count">{counts ? `${counts[t] ?? 0}건` : ""}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="dochist-main">
        <h2>
          {KIND_LABEL[docType]}
          {counts && <span className="count"> {counts[docType] ?? 0}건</span>}
        </h2>
        {docType === "unknown" && (
          <p className="hint dochist-note">종류를 정하지 못했거나 분류에 실패한 서류입니다. 작업을 눌러 확인해 주세요.</p>
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
          <table className="cells doc-table">
            <thead>
              <tr>
                <th>파일 이름</th>
                <th>작업</th>
                <th>서류 번호</th>
                <th>수하인</th>
                <th>분류 근거</th>
                <th>분류</th>
                <th>작업 상태</th>
                <th>올린 날짜</th>
              </tr>
            </thead>
            <tbody>
              {items.map((d, i) => (
                <tr key={`${d.job_id}-${d.file_name}-${i}`}>
                  <td data-label="파일 이름" className="doc-file">
                    {/* 누르면 서류 그림과 분류 근거를 여는 창 (G11) */}
                    <button type="button" className="link doc-open" aria-haspopup="dialog" onClick={() => setOpened(d)}>
                      {d.file_name}
                    </button>
                  </td>
                  <td data-label="작업">
                    <button type="button" className="link" onClick={() => navigate(`/jobs/${encodeURIComponent(d.job_id)}`)}>
                      {d.job_id}
                    </button>
                  </td>
                  <td data-label="서류 번호">{d.doc_no ?? <span className="hint">-</span>}</td>
                  <td data-label="수하인">{d.consignee ?? <span className="hint">-</span>}</td>
                  <td data-label="분류 근거" className="doc-reason">
                    {d.reason}
                  </td>
                  <td data-label="분류">{BY_KO[d.classified_by]}</td>
                  <td data-label="작업 상태">
                    <span className={`status status-${d.job_status}`}>{STATUS_KO[d.job_status]}</span>
                  </td>
                  <td data-label="올린 날짜">{d.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {query.hasNextPage && (
          <button
            type="button"
            className="more"
            disabled={query.isFetchingNextPage}
            onClick={() => query.fetchNextPage()}
          >
            {query.isFetchingNextPage ? "불러오는 중…" : "더 보기"}
          </button>
        )}
      </div>

      {opened && (
        <DocDetail
          record={opened}
          kindLabel={KIND_LABEL[opened.doc_type]}
          statusLabel={STATUS_KO[opened.job_status]}
          onClose={() => setOpened(null)}
        />
      )}
    </section>
  );
}
