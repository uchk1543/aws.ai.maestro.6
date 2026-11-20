// G11·G12 작업 화면 위변조 확인: 오류를 누르면 그 서류로 바꾸고 그 칸 박스와 읽은 칸 표의 줄을 강조한다
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import jobFilesExample from "../../../docs/examples/job_files.json";
import jobExample from "../../../docs/examples/job_waiting_approval.json";
import draft from "../fixtures/documents.draft.json";
import { fileViewOf } from "../mockDocs";
import { DOC_TYPE_KO, type DocumentRecord, type Issue, type Job, type JobFilesResponse } from "../types";
import { DocReview, hitsFor, locate } from "./DocReview";
import { pdfViewSrc } from "./DocViewer";

const issues = (jobExample as Job).result!.issues;
const files = (draft.items as DocumentRecord[]).filter((d) => d.job_id === "job-7c1e").map(fileViewOf);

function pressedMark() {
  return screen.queryAllByRole("button", { pressed: true }).find((b) => b.classList.contains("mark")) ?? null;
}

describe("DocReview", () => {
  it("처음에는 첫 오류의 첫 서류(상업송장)를 보여 주고 그 칸을 강조한다", () => {
    render(<DocReview jobId="job-7c1e" issues={issues} files={files} />);

    expect(screen.getByRole("tab", { name: /상업송장/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("img", { name: "invoice.pdf 1쪽" })).toBeInTheDocument();
    const mark = pressedMark();
    expect(mark).toHaveAccessibleName("불일치 · 1행 총중량: 6,250.00 KGS");
    expect(mark).toHaveClass("mark-mismatch");
  });

  it("서류별 값을 누르면 그 서류로 바뀌고 그 칸이 강조된다", async () => {
    const user = userEvent.setup();
    render(<DocReview jobId="job-7c1e" issues={issues} files={files} />);

    await user.click(screen.getByRole("button", { name: /포장명세서.*6,520\.00 KGS/ }));

    expect(screen.getByRole("tab", { name: /포장명세서/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("img", { name: "packing.pdf 1쪽" })).toBeInTheDocument();
    expect(pressedMark()).toHaveAccessibleName("불일치 · 1행 총중량: 6,520.00 KGS");
  });

  it("탭으로 오류가 없는 서류를 보면 강조 박스가 없다", async () => {
    const user = userEvent.setup();
    render(<DocReview jobId="job-7c1e" issues={issues} files={files} />);

    await user.click(screen.getByRole("tab", { name: "선하증권" }));

    expect(screen.getByRole("img", { name: "bl.jpg 1쪽" })).toBeInTheDocument();
    expect(pressedMark()).toBeNull();
  });

  it("위치를 못 찾은 칸은 알린다", () => {
    const noMark: Issue = { ...issues[0], cells: [{ doc: "commercial_invoice", field: "items[0].amount", raw: "USD 1.00" }] };
    render(<DocReview jobId="job-7c1e" issues={[noMark]} files={files} />);

    expect(screen.getByRole("status")).toHaveTextContent("이 칸(items[0].amount)의 위치를 찾지 못했습니다.");
  });

  it("등급 글자와 근거 문장, raw 는 서버 값 그대로", () => {
    render(<DocReview jobId="job-7c1e" issues={issues} files={files} />);
    const item = within(screen.getByRole("list", { name: "오류" })).getByRole("listitem");

    expect(within(item).getByText("불일치")).toBeInTheDocument();
    expect(within(item).getByText("상업송장 1행 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다.")).toBeInTheDocument();
    expect(item).toHaveTextContent("Textract OCR로 다시 확인");
  });

  it("locate 는 서류 종류와 칸 이름이 같은 표시를 찾는다", () => {
    expect(locate(files, { doc: "packing_list", field: "items[0].gross_kg", raw: null }).mark?.text).toBe("6,520.00 KGS");
    expect(locate(files, { doc: "certificate_of_origin", field: "doc_no", raw: null })).toEqual({ file: null, mark: null });
  });

  it("강조한 박스에는 근거 문장과 서류별 값을 담은 작은 팝업이 뜬다", () => {
    render(<DocReview jobId="job-7c1e" issues={issues} files={files} />);

    const pop = screen.getByRole("dialog", { name: "불일치 · 1행 총중량" });
    expect(pop).toHaveTextContent("6,250.00 KGS");
    expect(pop).toHaveTextContent("상업송장 1행 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다.");
    expect(pop).toHaveTextContent("포장명세서 6,520.00 KGS");
  });

  it("쪽 그림이 없으면 원본 주소를 그대로 띄운다 (PDF 는 iframe, 이미지는 img)", () => {
    const pdf = { ...files[0], pages: [], marks: [], url: "https://s3.test/inv.pdf", content_type: "application/pdf" };
    const png = { ...files[1], pages: [], marks: [], url: "https://s3.test/pl.png", content_type: "image/png" };
    const { unmount } = render(<DocReview jobId="job-7c1e" issues={issues} files={[pdf, png]} />);
    // 브라우저 PDF 보기의 검은 도구 막대·쪽 목록을 끄고 쪽 너비에 맞춘다 (G12)
    expect(screen.getByTitle("invoice.pdf 원본")).toHaveAttribute("src", "https://s3.test/inv.pdf#toolbar=0&navpanes=0&statusbar=0&messages=0&view=FitH");
    unmount();

    render(<DocReview jobId="job-7c1e" issues={[{ ...issues[0], cells: [issues[0].cells[1]] }]} files={[pdf, png]} />);
    expect(screen.getByRole("img", { name: "packing.pdf 원본" })).toHaveAttribute("src", "https://s3.test/pl.png");
  });

  it("서버 예시(docs/examples/job_files.json, F7)를 그대로 받아 그린다", () => {
    const real = (jobFilesExample as unknown as JobFilesResponse).files;
    render(<DocReview jobId="job-7c1e" issues={issues} files={real} />);
    expect(screen.getByRole("tablist", { name: "서류" })).toBeInTheDocument();
    // 탭 글자 = 서류 종류 + 오류 칸 수(있을 때)
    expect(screen.getAllByRole("tab").map((t) => t.textContent?.replace(/\d+$/, ""))).toEqual(real.map((f) => DOC_TYPE_KO[f.doc_type]));
  });

  it("오른쪽 아래에 지금 보는 서류의 읽은 칸 표를 두고, 오류가 짚은 칸은 등급 색·근거 문장·확인 방법을 붙인다 (G12)", () => {
    render(<DocReview jobId="job-7c1e" issues={issues} files={files} />);

    const table = within(screen.getByRole("region", { name: "상업송장 읽은 칸" })).getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.length).toBe(files[0].fields!.length);
    const hit = rows.find((r) => r.textContent?.includes("items[0].gross_kg"))!;
    expect(hit).toHaveClass("row-mismatch", "active");
    expect(hit).toHaveTextContent("상업송장 1행 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다.");
    expect(hit).toHaveTextContent("Textract OCR로 다시 확인");
    // 오류가 없는 칸은 색이 없다
    expect(rows.filter((r) => r.className.includes("row-")).length).toBe(1);
  });

  it("오류 값을 누르면 그 서류의 읽은 칸 표로 바뀌고 그 줄을 짚는다", async () => {
    const user = userEvent.setup();
    render(<DocReview jobId="job-7c1e" issues={issues} files={files} />);

    await user.click(screen.getByRole("button", { name: /포장명세서.*6,520\.00 KGS/ }));

    const region = screen.getByRole("region", { name: "포장명세서 읽은 칸" });
    const active = within(region).getAllByRole("row").find((r) => r.getAttribute("aria-current") === "true");
    expect(active).toHaveTextContent("6,520.00 KGS");
  });

  it("읽은 칸이 없으면 빈 문장", () => {
    render(<DocReview jobId="job-7c1e" issues={issues} files={files.map((f) => ({ ...f, fields: [] }))} />);
    expect(screen.getByText("이 서류의 읽은 칸이 없습니다.")).toBeInTheDocument();
  });

  it("관리자에게 보낼 문서는 서버의 통지 문서 주소로 내려받는다 (html, md)", () => {
    render(<DocReview jobId="job-7c1e" issues={issues} files={files} />);
    const link = screen.getByRole("link", { name: "관리자에게 보낼 문서 받기" });
    expect(link).toHaveAttribute("href", "/api/jobs/job-7c1e/notice?format=html");
    expect(link).toHaveAttribute("download");
    expect(link).toHaveAccessibleDescription("검토한 뒤 보내세요");
    expect(screen.getByRole("link", { name: "관리자에게 보낼 문서 마크다운으로 받기" })).toHaveAttribute(
      "href",
      "/api/jobs/job-7c1e/notice?format=md",
    );
    expect(screen.queryByText("준비 중")).not.toBeInTheDocument();
  });

  it("hitsFor 는 같은 칸을 여러 오류가 짚으면 앞(등급이 높은) 오류를 쓴다", () => {
    const cell = issues[0].cells[0];
    const second: Issue = { ...issues[0], grade: "확인 필요", evidence: "두 번째" };
    const hits = hitsFor([issues[0], second], cell.doc);
    expect(hits.get(cell.field)?.issue.evidence).toBe(issues[0].evidence);
  });

  it("pdfViewSrc 는 주소의 ?조건은 두고 #조각만 바꾼다", () => {
    expect(pdfViewSrc("https://s3.test/a.pdf?X-Amz-Signature=1#page=2")).toBe(
      "https://s3.test/a.pdf?X-Amz-Signature=1#toolbar=0&navpanes=0&statusbar=0&messages=0&view=FitH",
    );
  });
});
