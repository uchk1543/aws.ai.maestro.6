// 작은 인라인 SVG 아이콘 (라이브러리 없이). 장식용이라 항상 aria-hidden 이고, 뜻은 옆의 글자나 aria-label 이 전한다.
import type { ReactNode } from "react";

export type IconName = "upload" | "list" | "chat" | "plus" | "close" | "chevron" | "arrow-up";

// 24x24 칸에 가는 선으로 그린다 (stroke = currentColor)
const PATHS: Record<IconName, ReactNode> = {
  upload: <path d="M12 15V4M7 9l5-5 5 5M5 15v4h14v-4" />,
  list: <path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01" />,
  chat: <path d="M5 5h14v10H10l-5 4z" />,
  plus: <path d="M12 5v14M5 12h14" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  chevron: <path d="M9 6l6 6-6 6" />,
  "arrow-up": <path d="M12 19V5M6 11l6-6 6 6" />,
};

export function Icon({ name, size = 22 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
