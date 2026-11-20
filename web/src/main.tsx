// 화면 시작점
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// 글꼴: Pretendard(OFL). 빌드에 글꼴 파일이 함께 들어가고, 브라우저는 쓰는 글자 조각만 받는다.
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import { App } from "./App";
import "./styles.css";

// 서버 상태(작업 조회 등)는 TanStack Query 가 들고 있다. 폴링 주기는 화면마다 정한다.
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
