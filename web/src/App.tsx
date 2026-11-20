// 메뉴 + 화면 (web/README.md 구조).
// 모바일: 위 앱 바 + 아래 탭 메뉴, 태블릿: 왼쪽 좁은 메뉴, PC: 왼쪽 메뉴. 배치는 styles.css 가 화면 너비로 바꾼다.
import type { ReactNode } from "react";
import { Icon, type IconName } from "./components/Icon";
import { ChatPage } from "./pages/ChatPage";
import { JobPage } from "./pages/JobPage";
import { UploadPage } from "./pages/UploadPage";
import { navigate, useHashPath } from "./route";

const APP_NAME = "통관 서류 검토";

type MenuKey = "upload" | "chat";

const MENU: { key: MenuKey; path: string; label: string; icon: IconName }[] = [
  { key: "upload", path: "/upload", label: "파일 업로드", icon: "upload" },
  { key: "chat", path: "/chat", label: "AI chat", icon: "chat" },
];

/** 해시 경로 → 보여 줄 화면, 켜 둘 메뉴, 앱 바에 적을 화면 제목. 모르는 경로는 첫 화면(업로드)으로 본다. */
function resolve(path: string): { page: ReactNode; active: MenuKey | null; title: string } {
  const job = path.match(/^\/jobs\/([^/]+)$/);
  if (job) {
    const jobId = decodeURIComponent(job[1]);
    return { page: <JobPage key={jobId} jobId={jobId} />, active: null, title: `작업 ${jobId}` };
  }
  if (path === "/chat") return { page: <ChatPage />, active: "chat", title: "AI chat" };
  return { page: <UploadPage />, active: "upload", title: "파일 업로드" };
}

export function App() {
  const { page, active, title } = resolve(useHashPath());
  return (
    <div className="layout">
      {/* 모바일에서만 보인다. 화면 제목(h1)은 각 화면에 있으므로 여기는 제목 역할을 주지 않는다 */}
      <header className="appbar">
        <span className="appbar-name">{APP_NAME}</span>
        <span className="appbar-title" aria-hidden="true">
          {title}
        </span>
      </header>
      <nav className="menu" aria-label="메뉴">
        <div className="menu-brand" aria-hidden="true">
          {APP_NAME}
        </div>
        {MENU.map((m) => (
          <button
            key={m.key}
            type="button"
            className={m.key === active ? "menu-item active" : "menu-item"}
            aria-current={m.key === active ? "page" : undefined}
            onClick={() => navigate(m.path)}
          >
            <Icon name={m.icon} size={22} />
            <span className="menu-label">{m.label}</span>
          </button>
        ))}
      </nav>
      <main className="content">{page}</main>
    </div>
  );
}
