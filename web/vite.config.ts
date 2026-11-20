// 화면 빌드·개발 서버·테스트 설정 (web/README.md G1)
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { loadEnv, searchForWorkspaceRoot, type Plugin } from "vite";
import { defineConfig } from "vitest/config";

const examples = fileURLToPath(new URL("../docs/examples", import.meta.url));

/** 가짜 모드(npm run dev)에서 내려받기 링크가 부르는 서버 경로를 흉내 낸다.
 *  화면은 이 경로를 fetch 가 아니라 <a download> 로 열어서 mock.ts 가 가로챌 수 없다.
 *  GET /api/jobs/{id}/notice?format=html|md → docs/examples/notice.json 의 html·markdown (빌드에는 들어가지 않는다) */
function mockDownloads(): Plugin {
  return {
    name: "mock-downloads",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const m = req.url?.match(/^\/api\/jobs\/([^/?]+)\/notice(?:\?format=(md|html))?/);
        if (req.method !== "GET" || !m) return next();
        const notice = JSON.parse(readFileSync(`${examples}/notice.json`, "utf-8"));
        const md = m[2] === "md";
        res.setHeader("content-type", md ? "text/markdown; charset=utf-8" : "text/html; charset=utf-8");
        res.setHeader("content-disposition", `attachment; filename="notice-${decodeURIComponent(m[1])}.${md ? "md" : "html"}"`);
        res.end(md ? notice.markdown : notice.html);
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  // npm run dev:api 일 때만 /api 를 배포된 CloudFront 주소로 보낸다
  const proxyTarget = loadEnv(mode, process.cwd(), "VITE_").VITE_API_PROXY;
  return {
    plugins: mode === "mock" ? [react(), mockDownloads()] : [react()],
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
