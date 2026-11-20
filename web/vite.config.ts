// 화면 빌드·개발 서버·테스트 설정 (web/README.md G1)
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { loadEnv, searchForWorkspaceRoot } from "vite";
import { defineConfig } from "vitest/config";

const examples = fileURLToPath(new URL("../docs/examples", import.meta.url));

export default defineConfig(({ mode }) => {
  // npm run dev:api 일 때만 /api 를 배포된 CloudFront 주소로 보낸다
  const proxyTarget = loadEnv(mode, process.cwd(), "VITE_").VITE_API_PROXY;
  return {
    plugins: [react()],
    server: {
      // 가짜 응답이 저장소의 docs/examples/*.json 을 직접 읽는다
      fs: { allow: [searchForWorkspaceRoot(process.cwd()), examples] },
      proxy: proxyTarget ? { "/api": { target: proxyTarget, changeOrigin: true } } : undefined,
    },
    build: { outDir: "dist" },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test-setup.ts"],
    },
  };
});
