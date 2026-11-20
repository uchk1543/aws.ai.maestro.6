// G6 신고서 초안 표: 채운 칸·출처, 비운 칸, "사람 검토 전 초안" 표시
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import jobExample from "../../../docs/examples/job_waiting_approval.json";
import type { Job } from "../types";
import { DeclarationTable } from "./DeclarationTable";

const exampleDraft = (jobExample as Job).result!.declaration_draft;

describe("DeclarationTable", () => {
  it("예시의 칸·값·출처와 비운 칸을 보여 준다", () => {
    render(<DeclarationTable draft={exampleDraft} />);

    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("품명");
    expect(rows[0]).toHaveTextContent("LITHIUM-ION BATTERY PACK");
    expect(rows[0]).toHaveTextContent("commercial_invoice.items[0].name");

    expect(screen.getByText("비워 둔 칸 (1)")).toBeInTheDocument();
    expect(screen.getByText("items[0].gross_kg")).toBeInTheDocument();
  });

  it("초안이 있든 없든 '사람 검토 전 초안'을 적는다", () => {
    const { unmount } = render(<DeclarationTable draft={exampleDraft} />);
    expect(screen.getByRole("note")).toHaveTextContent("사람 검토 전 초안");
    unmount();

    render(<DeclarationTable draft={null} />);
    expect(screen.getByRole("note")).toHaveTextContent("사람 검토 전 초안");
    expect(screen.getByText("아직 신고서 초안이 없습니다.")).toBeInTheDocument();
  });

  it("PDF 주소는 http(s)일 때만 링크로 보여 준다", () => {
    const { unmount } = render(
      <DeclarationTable draft={{ fields: [], blank_fields: [], pdf_url: "https://example.com/draft.pdf" }} />,
    );
    expect(screen.getByRole("link", { name: "PDF 받기" })).toHaveAttribute("href", "https://example.com/draft.pdf");
    unmount();

    render(<DeclarationTable draft={{ fields: [], blank_fields: [], pdf_url: "javascript:alert(1)" }} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("값이 null 인 칸은 '(값 없음)'", () => {
    render(<DeclarationTable draft={{ fields: [{ name: "총중량", value: null, source: "packing_list.total_gross_kg" }], blank_fields: [], pdf_url: null }} />);
    expect(screen.getByText("(값 없음)")).toBeInTheDocument();
  });
});
