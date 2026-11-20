// G11 작업 화면 오류 보기: 오류를 누르면 그 서류로 바꾸고 그 칸 박스를 강조한다
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import jobExample from "../../../docs/examples/job_waiting_approval.json";
import draft from "../fixtures/documents.draft.json";
import { fileViewOf } from "../mockDocs";
import type { DocumentRecord, Issue, Job } from "../types";
import { DocReview, locate } from "./DocReview";
import { boxStyle } from "./DocViewer";

const issues = (jobExample as Job).result!.issues;
const files = (draft.items as DocumentRecord[]).filter((d) => d.job_id === "job-7c1e").map(fileViewOf);

function pressedMark() {
  return screen.queryAllByRole("button", { pressed: true }).find((b) => b.classList.contains("mark")) ?? null;
}

describe("DocReview", () => {
  it("처음에는 첫 오류의 첫 서류(상업송장)를 보여 주고 그 칸을 강조한다", () => {
    render(<DocReview issues={issues} files={files} />);

    expect(screen.getByRole("tab", { name: /상업송장/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("img", { name: "invoice.pdf 1쪽" })).toBeInTheDocument();
    const mark = pressedMark();
    expect(mark).toHaveAccessibleName("불일치 · 1행 총중량: 6,250.00 KGS");
    expect(mark).toHaveClass("mark-mismatch");
  });

  it("서류별 값을 누르면 그 서류로 바뀌고 그 칸이 강조된다", async () => {
    const user = userEvent.setup();
    render(<DocReview issues={issues} files={files} />);

    await user.click(screen.getByRole("button", { name: /포장명세서.*6,520\.00 KGS/ }));

    expect(screen.getByRole("tab", { name: /포장명세서/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("img", { name: "packing.pdf 1쪽" })).toBeInTheDocument();
    expect(pressedMark()).toHaveAccessibleName("불일치 · 1행 총중량: 6,520.00 KGS");
  });

  it("탭으로 오류가 없는 서류를 보면 강조 박스가 없다", async () => {
    const user = userEvent.setup();
    render(<DocReview issues={issues} files={files} />);

    await user.click(screen.getByRole("tab", { name: "선하증권" }));

    expect(screen.getByRole("img", { name: "bl.jpg 1쪽" })).toBeInTheDocument();
    expect(pressedMark()).toBeNull();
  });

  it("위치를 못 찾은 칸은 알린다", () => {
    const noMark: Issue = { ...issues[0], cells: [{ doc: "commercial_invoice", field: "items[0].amount", raw: "USD 1.00" }] };
    render(<DocReview issues={[noMark]} files={files} />);

    expect(screen.getByRole("status")).toHaveTextContent("이 칸(items[0].amount)의 위치를 찾지 못했습니다.");
  });

  it("등급 글자와 근거 문장, raw 는 서버 값 그대로", () => {
    render(<DocReview issues={issues} files={files} />);
    const item = within(screen.getByRole("list", { name: "오류" })).getByRole("listitem");

    expect(within(item).getByText("불일치")).toBeInTheDocument();
    expect(within(item).getByText("상업송장 1행 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다.")).toBeInTheDocument();
    expect(item).toHaveTextContent("Textract OCR로 다시 확인");
  });

  it("locate 는 서류 종류와 칸 이름이 같은 표시를 찾는다", () => {
    expect(locate(files, { doc: "packing_list", field: "items[0].gross_kg", raw: null }).mark?.text).toBe("6,520.00 KGS");
    expect(locate(files, { doc: "certificate_of_origin", field: "doc_no", raw: null })).toEqual({ file: null, mark: null });
  });

  it("boxStyle 은 0~1 비율을 % 로 바꾸고 밖으로 나간 값은 자른다", () => {
    expect(boxStyle([0.1, 0.2, 0.3, 0.05])).toEqual({ left: "10.000%", top: "20.000%", width: "30.000%", height: "5.000%" });
    expect(boxStyle([0.9, -0.1, 0.5, 0.2])).toEqual({ left: "90.000%", top: "0.000%", width: "10.000%", height: "20.000%" });
  });
});
