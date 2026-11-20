// G4 오류 목록: 등급·근거·서류·칸·raw·확인 방법
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import jobExample from "../../../docs/examples/job_waiting_approval.json";
import type { Issue, Job } from "../types";
import { IssueList, sortByGrade } from "./IssueList";

const exampleIssues = (jobExample as Job).result!.issues;

const issue = (grade: Issue["grade"], rule_id: string, extra: Partial<Issue> = {}): Issue => ({
  rule_id,
  grade,
  cells: [],
  suspect: null,
  evidence: `${rule_id} 근거`,
  checked_by: "none",
  ...extra,
});

describe("IssueList", () => {
  it("예시의 등급·근거·서류·칸·raw·확인 방법을 보여 준다", () => {
    render(<IssueList issues={exampleIssues} />);

    expect(screen.getByText("오류 목록 (1)")).toBeInTheDocument();
    const item = screen.getByRole("listitem");
    expect(within(item).getByText("불일치")).toBeInTheDocument();
    expect(within(item).getByText("상업송장 1행 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다.")).toBeInTheDocument();

    const rows = within(item).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("상업송장");
    expect(rows[0]).toHaveTextContent("items[0].gross_kg");
    expect(rows[0]).toHaveTextContent("6,250.00 KGS");
    expect(rows[1]).toHaveTextContent("포장명세서");
    expect(rows[1]).toHaveTextContent("6,520.00 KGS");

    expect(within(item).getByText("X-WT-01")).toBeInTheDocument();
    expect(item).toHaveTextContent("Textract OCR로 다시 확인");
  });

  it("못 읽은 칸(raw null)은 '못 읽음', suspect 서류는 (의심) 표시", () => {
    render(
      <IssueList
        issues={[
          issue("확인 필요", "X-QTY-01", {
            suspect: "packing_list",
            cells: [
              { doc: "commercial_invoice", field: "total_qty", raw: "2,650 PCS" },
              { doc: "bill_of_lading", field: "total_qty", raw: "2,650 PCS" },
              { doc: "packing_list", field: "total_qty", raw: null },
            ],
          }),
        ]}
      />,
    );

    expect(screen.getByText("못 읽음")).toBeInTheDocument();
    expect(screen.getByText("(의심)", { exact: false }).closest("tr")).toHaveTextContent("포장명세서");
    expect(screen.getByRole("listitem")).toHaveTextContent("다른 서류와 다른 쪽: 포장명세서");
  });

  it("문제가 없으면 없다고 보여 준다", () => {
    render(<IssueList issues={[]} />);
    expect(screen.getByText("찾은 문제가 없습니다.")).toBeInTheDocument();
  });

  it("불일치 → 확인 필요 → 참고 순서, 같은 등급은 서버 순서 유지", () => {
    const sorted = sortByGrade([
      issue("참고", "N-1"),
      issue("확인 필요", "C-1"),
      issue("불일치", "M-1"),
      issue("확인 필요", "C-2"),
    ]);
    expect(sorted.map((i) => i.rule_id)).toEqual(["M-1", "C-1", "C-2", "N-1"]);
  });
});
