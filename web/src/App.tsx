// 왼쪽 메뉴 + 오른쪽 화면 (web/README.md 구조)
import type { ReactNode } from "react";
import { ChatPage } from "./pages/ChatPage";
import { JobPage } from "./pages/JobPage";
import { UploadPage } from "./pages/UploadPage";
import { navigate, useHashPath } from "./route";

type MenuKey = "upload" | "chat";

const MENU: { key: MenuKey; path: string; label: string }[] = [
  { key: "upload", path: "/upload", label: "파일 업로드" },
  { key: "chat", path: "/chat", label: "AI chat" },
];

/** 해시 경로 → 보여 줄 화면과 켜 둘 메뉴. 모르는 경로는 첫 화면(업로드)으로 본다. */
function resolve(path: string): { page: ReactNode; active: MenuKey | null } {
  const job = path.match(/^\/jobs\/([^/]+)$/);
  if (job) {
    const jobId = decodeURIComponent(job[1]);
    return { page: <JobPage key={jobId} jobId={jobId} />, active: null };
  }
  if (path === "/chat") return { page: <ChatPage />, active: "chat" };
  return { page: <UploadPage />, active: "upload" };
}

export function App() {
  const { page, active } = resolve(useHashPath());
  return (
    <div className="layout">
      <nav className="menu" aria-label="메뉴">
        {MENU.map((m) => (
          <button
            key={m.key}
            type="button"
            className={m.key === active ? "menu-item active" : "menu-item"}
            aria-current={m.key === active ? "page" : undefined}
            onClick={() => navigate(m.path)}
          >
            {m.label}
          </button>
        ))}
      </nav>
      <main className="content">{page}</main>
    </div>
  );
}
