// FB22: 서버가 next_action 을 주지 않을 때 화면이 같은 규칙으로 정한다 (tools/wms.py next_action 과 같은 순서)
import { describe, expect, it } from "vitest";
import { nextActionOf } from "./nextAction";
import type { HSResult, Issue, Job } from "./types";

const issue = (grade: Issue["grade"]): Issue => ({ rule_id: "R", grade, cells: [], suspect: null, evidence: "근거", checked_by: "none" });
const pending: HSResult = { line: 1, status: "사람 확인 필요", by: null, hs_code: null, candidates: [] };
const done: HSResult = { line: 2, status: "자동 확정", by: "history", hs_code: "8507609000", candidates: [] };
const job = (issues: Issue[], hs: HSResult[], extra: Partial<Job> = {}): Job => ({
  job_id: "job-0000abcd",
  status: "waiting_approval",
  steps: [],
  result: { issues, hs, declaration_draft: null, wms: null },
  ...extra,
});

describe("nextActionOf", () => {
  it("서버 값이 있으면 그대로 쓴다", () => {
    const given = { kind: "approve", message: "서버 문장", count: null } as const;
    expect(nextActionOf(job([issue("불일치")], [], { next_action: given }))).toBe(given);
  });

  it("불일치 → 고를 HS → 확인 필요 → 승인 순서로 가른다", () => {
    expect(nextActionOf(job([issue("불일치"), issue("확인 필요")], [pending])).message).toBe(
      "불일치 1건: 서류를 고쳐 다시 올리거나, 원본을 확인해 판독 오류면 사유를 적고 승인하세요",
    );
    expect(nextActionOf(job([issue("확인 필요")], [pending, { ...pending, line: 3 }])).message).toBe("HS 2개를 고르세요");
    expect(nextActionOf(job([issue("확인 필요"), issue("참고")], [done])).message).toBe("확인 필요 1건을 확인한 뒤 승인하세요");
    expect(nextActionOf(job([issue("참고")], [done])).message).toBe("확인한 뒤 승인하세요");
  });

  it("처리 중·실패·끝남", () => {
    expect(nextActionOf({ job_id: "j", status: "running", steps: [], result: null }).kind).toBe("wait");
    expect(nextActionOf({ job_id: "j", status: "failed", steps: [], result: null }).kind).toBe("reupload");
    expect(
      nextActionOf(job([], [done], { status: "done", result: { issues: [], hs: [done], declaration_draft: null, wms: { status: "등록됨", by: "auto", wms_id: "W" } } }))
        .message,
    ).toBe("WMS에 등록됐습니다. 더 할 일이 없습니다");
  });
});
