// 메뉴 + 화면 (web/README.md 구조).
// 메뉴는 모바일에서 아래 탭(아이콘 + 글자), 태블릿·PC 에서 위 왼쪽 칩이다. 배치는 styles.css 가 화면 너비로 바꾼다.
import type { ReactNode } from "react";
import { Icon, type IconName } from "./components/Icon";
import { ChatPage } from "./pages/ChatPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DocHistoryPage } from "./pages/DocHistoryPage";
import { JobPage } from "./pages/JobPage";
import { UploadPage } from "./pages/UploadPage";
import { navigate, splitHash, useHashPath } from "./route";

export const APP_NAME = "통관 서류 검토";

type MenuKey = "upload" | "documents" | "dashboard" | "chat";

const MENU: { key: MenuKey; path: string; label: string; icon: IconName }[] = [
  { key: "upload", path: "/upload", label: "파일 업로드", icon: "upload" },
  { key: "documents", path: "/documents", label: "문서 분류 내역", icon: "list" },
  { key: "dashboard", path: "/dashboard", label: "대시보드", icon: "chart" },
  { key: "chat", path: "/chat", label: "AI chat", icon: "chat" },
];

/** 해시 주소 → 보여 줄 화면과 켜 둘 메뉴. 모르는 경로는 첫 화면(업로드)으로 본다. ?조건은 화면에 넘긴다. */
function resolve(hash: string): { page: ReactNode; active: MenuKey | null } {
  const { path, params } = splitHash(hash);
  const job = path.match(/^\/jobs\/([^/]+)$/);
  if (job) {
    const jobId = decodeURIComponent(job[1]);
    return { page: <JobPage key={jobId} jobId={jobId} />, active: null };
  }
  // 조건이 바뀌면 화면을 새로 연다 (대시보드에서 다른 통계를 눌렀을 때)
  if (path === "/documents") return { page: <DocHistoryPage key={hash} params={params} />, active: "documents" };
  if (path === "/dashboard") return { page: <DashboardPage />, active: "dashboard" };
  if (path === "/chat") return { page: <ChatPage key={hash} ask={params.q} />, active: "chat" };
  return { page: <UploadPage />, active: "upload" };
}

export function App() {
  const { page, active } = resolve(useHashPath());
  return (
    <div className="layout">
      <header className="topbar">
        <span className="brand">{APP_NAME}</span>
        <nav className="menu" aria-label="메뉴">
          {MENU.map((m) => (
            <button
              key={m.key}
              type="button"
              className={m.key === active ? "menu-item active" : "menu-item"}
              aria-current={m.key === active ? "page" : undefined}
              onClick={() => navigate(m.path)}
            >
              <Icon name={m.icon} />
              <span>{m.label}</span>
            </button>
          ))}
        </nav>
      </header>
      <main className="content">{page}</main>
    </div>
  );
}
