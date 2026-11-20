// 해시 주소(#/upload, #/jobs/{id}, #/documents?grade=불일치). S3 에는 index.html 하나만 있어도 새로고침이 된다.
import { useSyncExternalStore } from "react";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

function currentHash(): string {
  return window.location.hash.replace(/^#/, "") || "/";
}

/** 지금 해시 주소 전체(경로 + ?조건). 예: "#/documents?grade=불일치" → "/documents?grade=불일치" */
export function useHashPath(): string {
  return useSyncExternalStore(subscribe, currentHash);
}

/** 해시 주소를 경로와 조건으로 나눈다. 예: "/documents?type=unknown" → { path: "/documents", params: {type: "unknown"} } */
export function splitHash(hash: string): { path: string; params: Record<string, string> } {
  const [path, query = ""] = hash.split("?");
  return { path: path || "/", params: Object.fromEntries(new URLSearchParams(query)) };
}

/** 경로와 조건으로 해시 주소를 만든다. 빈 조건은 뺀다. */
export function hashOf(path: string, params: Record<string, string | null | undefined> = {}): string {
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) query.set(k, v);
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

/** 다른 화면으로 간다. 예: navigate("/documents", { grade: "불일치" }) */
export function navigate(path: string, params?: Record<string, string | null | undefined>): void {
  window.location.hash = params ? hashOf(path, params) : path;
}
