// styles.css 의 괄호 짝 검사. 병합 충돌을 손으로 풀다 닫는 괄호가 빠지면 뒤 규칙이 모두 앞 규칙 안으로 들어가
// 조용히 적용되지 않는다 (#280·#281 병합 때 AI chat 표 규칙이 그렇게 빠졌다). 빌드와 다른 시험은 이를 잡지 못한다.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// 시험은 web/ 에서 돈다 (jsdom 이라 import.meta.url 이 file: 주소가 아니다)
const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf-8")
  .replace(/\/\*[\s\S]*?\*\//g, "") // 주석 안의 { } 는 세지 않는다
  .replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, '""'); // 문자열 안의 { } 도 세지 않는다

describe("styles.css", () => {
  it("여는 괄호와 닫는 괄호가 짝이 맞고, 중간에 닫는 괄호가 먼저 나오지 않는다", () => {
    let depth = 0;
    let lowest = 0;
    for (const ch of css) {
      if (ch === "{") depth += 1;
      if (ch === "}") depth -= 1;
      lowest = Math.min(lowest, depth);
    }
    expect(lowest).toBe(0);
    expect(depth).toBe(0);
  });

  it("병합 충돌 표시가 남아 있지 않다", () => {
    expect(css).not.toMatch(/^(<{7}|={7}|>{7})/m);
  });
});
