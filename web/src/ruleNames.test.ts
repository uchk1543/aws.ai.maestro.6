// G18 #255: 규칙 표의 규칙·등급마다 짧은 이름이 있고, 표의 설명보다 짧다
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { SHORT_RULE_KEYS, shortRuleName } from "./ruleNames";
import type { Grade } from "./types";

/** rules.csv 의 rule_id · grade · description (설명에 쉼표가 들어가도 앞 세 칸만 쓴다) */
// 시험은 web/ 에서 돈다 (npm test)
const rulesCsv = readFileSync("../tools/rules/rules.csv", "utf-8");
const rows = rulesCsv
  .trim()
  .split(/\r?\n/)
  .slice(1)
  .map((line) => {
    const [rule_id, grade, description] = line.split(",");
    return { rule_id, grade: grade as Grade, description };
  });

describe("shortRuleName", () => {
  it("규칙 표의 모든 규칙·등급에 짧은 이름이 있고, 설명보다 짧다", () => {
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) {
      expect(SHORT_RULE_KEYS, `${r.rule_id}:${r.grade}`).toContain(`${r.rule_id}:${r.grade}`);
      expect(shortRuleName(r.rule_id, r.grade, r.description).length).toBeLessThan(r.description.length);
    }
  });

  it("예: 총중량 불일치", () => {
    expect(shortRuleName("X-WT-01", "불일치", "서류끼리 서류 전체 총중량이 같은지")).toBe("서류 간 총중량 불일치");
  });

  it("모르는 규칙은 서버 이름, 없으면 예시 문장", () => {
    expect(shortRuleName("X-NEW-01", "불일치", "새 규칙 이름", "예시")).toBe("새 규칙 이름");
    expect(shortRuleName("X-NEW-01", "불일치", null, "예시 문장")).toBe("예시 문장");
  });
});
