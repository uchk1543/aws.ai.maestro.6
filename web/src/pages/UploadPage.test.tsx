// G2 업로드 화면: 여러 장 고르기, X로 빼기, 서류 종류 고치기, 업로드 순서
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { MAX_BYTES, UploadPage } from "./UploadPage";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, createUploads: vi.fn(), putToS3: vi.fn(), createJob: vi.fn() };
});

const pdf = (name: string) => new File(["%PDF"], name, { type: "application/pdf" });

function picker() {
  return screen.getByLabelText("파일 고르기") as HTMLInputElement;
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
    expect(screen.getByText("선택된 파일 (2)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "invoice.pdf 빼기" }));
    expect(screen.getByText("선택된 파일 (1)")).toBeInTheDocument();
    expect(screen.queryByText("invoice.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("packing.pdf")).toBeInTheDocument();
  });

  it("같은 파일을 두 번 골라도 한 번만 들어간다", async () => {
    const user = userEvent.setup();
    render(<UploadPage />);
    const file = pdf("invoice.pdf");

    await user.upload(picker(), file);
    await user.upload(picker(), file);

    expect(screen.getByText("선택된 파일 (1)")).toBeInTheDocument();
  });

  it("업로드: 주소 받기 → S3 PUT → 작업 만들기(고친 서류 종류, 자동 분류는 null) → 진행 화면", async () => {
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
    await user.selectOptions(screen.getAllByLabelText("서류 종류")[0], "상업송장");
    await user.click(screen.getByRole("button", { name: "업로드" }));

    await waitFor(() => expect(window.location.hash).toBe("#/jobs/job-0000abcd"));
    expect(api.createUploads).toHaveBeenCalledWith([
      { name: "invoice.pdf", content_type: "application/pdf" },
      { name: "packing.pdf", content_type: "application/pdf" },
    ]);
    expect(api.putToS3).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.putToS3).mock.calls[1][0]).toBe("https://s3/2");
    expect(api.createJob).toHaveBeenCalledWith([
      { key: "uploads/x/1-invoice.pdf", doc_type: "commercial_invoice" },
      { key: "uploads/x/2-packing.pdf", doc_type: null },
    ]);
  });

  it("서버 오류 문장을 보여 주고 다시 시도할 수 있다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createUploads).mockRejectedValue(new api.ApiError(501, "아직 만들지 않은 경로입니다 (F2)"));
    render(<UploadPage />);

    await user.upload(picker(), pdf("invoice.pdf"));
    await user.click(screen.getByRole("button", { name: "업로드" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("아직 만들지 않은 경로입니다 (F2)");
    expect(screen.getByRole("button", { name: "업로드" })).toBeEnabled();
    expect(api.createJob).not.toHaveBeenCalled();
  });

  it("파일이 없거나 너무 크면 업로드 버튼이 꺼진다", async () => {
    const user = userEvent.setup();
    render(<UploadPage />);
    expect(screen.getByRole("button", { name: "업로드" })).toBeDisabled();

    const big = new File([new Uint8Array(MAX_BYTES + 1)], "big.png", { type: "image/png" });
    await user.upload(picker(), big);

    expect(screen.getByText("· 너무 큽니다", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "업로드" })).toBeDisabled();
  });
});
