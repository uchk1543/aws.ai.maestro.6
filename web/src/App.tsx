// 왼쪽 메뉴 + 오른쪽 화면 (web/README.md 구조)
import type { ReactNode } from "react";
import { UploadPage } from "./pages/UploadPage";
import { navigate, useHashPath } from "./route";

type MenuKey = "upload";

const MENU: { key: MenuKey; path: string; label: string }[] = [
  { key: "upload", path: "/upload", label: "파일 업로드" },
];

/** 해시 경로 → 보여 줄 화면과 켜 둘 메뉴. 모르는 경로는 첫 화면(업로드)으로 본다. */
function resolve(path: string): { page: ReactNode; active: MenuKey | null } {
  const job = path.match(/^\/jobs\/([^/]+)$/);
  if (job) {
    const jobId = decodeURIComponent(job[1]);
    // 진행·결과 화면은 G3 에서 채운다
    return {
      page: (
        <section>
          <h1>작업 {jobId}</h1>
          <p>작업을 만들었습니다.</p>
        </section>
      ),
      active: null,
    };
  }
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
