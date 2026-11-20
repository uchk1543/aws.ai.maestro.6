// 해시 주소: 경로와 ?조건 나누기·만들기 (G15)
import { describe, expect, it } from "vitest";
import { hashOf, splitHash } from "./route";

describe("route", () => {
  it("splitHash 는 경로와 조건을 나눈다", () => {
    expect(splitHash("/documents?grade=%EB%B6%88%EC%9D%BC%EC%B9%98&type=unknown")).toEqual({
      path: "/documents",
      params: { grade: "불일치", type: "unknown" },
    });
    expect(splitHash("/jobs/job-7c1e")).toEqual({ path: "/jobs/job-7c1e", params: {} });
  });

  it("hashOf 는 빈 조건을 빼고 주소를 만든다", () => {
    expect(hashOf("/documents", { job_status: "waiting_approval", grade: undefined, rule_id: "" })).toBe("/documents?job_status=waiting_approval");
    expect(hashOf("/chat")).toBe("/chat");
    expect(splitHash(hashOf("/chat", { q: "심사 중 화물 전체 알려줘" })).params.q).toBe("심사 중 화물 전체 알려줘");
  });
});
