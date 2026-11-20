// G2·G9 업로드 화면: 여러 장 고르기, X로 빼기, 끌어다 놓기, 형식 검사, 업로드 순서(서류 종류는 모두 자동 분류)
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { isAllowedFile, MAX_BYTES, UploadPage } from "./UploadPage";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, createUploads: vi.fn(), putToS3: vi.fn(), createJob: vi.fn() };
});

const pdf = (name: string) => new File(["%PDF"], name, { type: "application/pdf" });

function picker() {
  return screen.getByLabelText("파일 고르기") as HTMLInputElement;
}

function countHeading(n: number) {
  return screen.getByRole("heading", { name: `선택된 파일 ${n}` });
}

beforeEach(() => {
  vi.mocked(api.createUploads).mockReset();
  vi.mocked(api.putToS3).mockReset();
  vi.mocked(api.createJob).mockReset();
});

describe("UploadPage", () => {
  it("여러 장을 고르면 목록에 보이고 X로 하나를 뺄 수 있다", async () => {
    const user = userEvent.setup();
    render(<UploadPage />);

    await user.upload(picker(), [pdf("invoice.pdf"), pdf("packing.pdf")]);
    expect(countHeading(2)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2개 업로드" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "invoice.pdf 빼기" }));
    expect(countHeading(1)).toBeInTheDocument();
    expect(screen.queryByText("invoice.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("packing.pdf")).toBeInTheDocument();
  });

  it("서류 종류를 고르는 칸은 없다 (자동 분류)", async () => {
    const user = userEvent.setup();
    render(<UploadPage />);

    await user.upload(picker(), pdf("invoice.pdf"));
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("같은 파일을 두 번 골라도 한 번만 들어간다", async () => {
    const user = userEvent.setup();
    render(<UploadPage />);
    const file = pdf("invoice.pdf");

    await user.upload(picker(), file);
    await user.upload(picker(), file);

    expect(countHeading(1)).toBeInTheDocument();
  });

  it("끌어다 놓으면 PDF·PNG·JPG 만 넣고, 나머지는 몇 개 뺐는지 알린다", () => {
    const { container } = render(<UploadPage />);
    const zone = container.querySelector(".file-pick")!;
    const files = [pdf("invoice.pdf"), new File(["x"], "scan.JPG", { type: "image/jpeg" }), new File(["x"], "memo.txt")];

    fireEvent.dragOver(zone, { dataTransfer: { files } });
    expect(zone).toHaveClass("dragging");
    fireEvent.drop(zone, { dataTransfer: { files } });

    expect(zone).not.toHaveClass("dragging");
    expect(countHeading(2)).toBeInTheDocument();
    expect(screen.getByText("scan.JPG")).toBeInTheDocument();
    expect(screen.queryByText("memo.txt")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("1개는 넣지 않았습니다");
  });

  it("isAllowedFile 은 확장자만 보고 대소문자를 가리지 않는다", () => {
    expect(isAllowedFile("a.pdf")).toBe(true);
    expect(isAllowedFile("A.PNG")).toBe(true);
    expect(isAllowedFile("b.jpeg")).toBe(true);
    expect(isAllowedFile("c.pdf.exe")).toBe(false);
    expect(isAllowedFile("d.heic")).toBe(false);
  });

  it("업로드: 주소 받기 → S3 PUT → 작업 만들기(doc_type 은 모두 null) → 진행 화면", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createUploads).mockResolvedValue({
      uploads: [
        { key: "uploads/x/1-invoice.pdf", url: "https://s3/1" },
        { key: "uploads/x/2-packing.pdf", url: "https://s3/2" },
      ],
    });
    vi.mocked(api.putToS3).mockResolvedValue();
    vi.mocked(api.createJob).mockResolvedValue({ job_id: "job-0000abcd" });
    render(<UploadPage />);

    await user.upload(picker(), [pdf("invoice.pdf"), pdf("packing.pdf")]);
    await user.click(screen.getByRole("button", { name: "2개 업로드" }));

    await waitFor(() => expect(window.location.hash).toBe("#/jobs/job-0000abcd"));
    expect(api.createUploads).toHaveBeenCalledWith([
      { name: "invoice.pdf", content_type: "application/pdf" },
      { name: "packing.pdf", content_type: "application/pdf" },
    ]);
    expect(api.putToS3).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.putToS3).mock.calls[1][0]).toBe("https://s3/2");
    expect(api.createJob).toHaveBeenCalledWith([
      { key: "uploads/x/1-invoice.pdf", doc_type: null },
      { key: "uploads/x/2-packing.pdf", doc_type: null },
    ]);
  });

  it("서버 오류 문장을 보여 주고 다시 시도할 수 있다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createUploads).mockRejectedValue(new api.ApiError(501, "아직 만들지 않은 경로입니다 (F2)"));
    render(<UploadPage />);

    await user.upload(picker(), pdf("invoice.pdf"));
    await user.click(screen.getByRole("button", { name: "1개 업로드" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("아직 만들지 않은 경로입니다 (F2)");
    expect(screen.getByRole("button", { name: "1개 업로드" })).toBeEnabled();
    expect(api.createJob).not.toHaveBeenCalled();
  });

  it("파일이 없거나 너무 크면 업로드 버튼이 꺼진다", async () => {
    const user = userEvent.setup();
    render(<UploadPage />);
    expect(screen.getByRole("button", { name: "업로드" })).toBeDisabled();

    const big = new File([new Uint8Array(MAX_BYTES + 1)], "big.png", { type: "image/png" });
    await user.upload(picker(), big);

    expect(screen.getByText("· 너무 큽니다", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1개 업로드" })).toBeDisabled();
  });
});
