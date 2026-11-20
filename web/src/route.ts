// 해시 주소(#/upload, #/jobs/{id}). S3 에는 index.html 하나만 있어도 새로고침이 된다.
import { useSyncExternalStore } from "react";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

function currentPath(): string {
  return window.location.hash.replace(/^#/, "") || "/";
}

/** 지금 해시 주소의 경로. 예: "#/jobs/job-7c1e" → "/jobs/job-7c1e" */
export function useHashPath(): string {
  return useSyncExternalStore(subscribe, currentPath);
}

/** 다른 화면으로 간다. */
export function navigate(path: string): void {
  window.location.hash = path;
}
