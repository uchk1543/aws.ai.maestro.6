// G7 WMS 상태와 승인: 상태 표시, 승인 요청, 409 안내
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import jobExample from "../../../docs/examples/job_waiting_approval.json";
import * as api from "../api";
import { renderWithQuery } from "../test-utils";
import type { Job } from "../types";
import { WmsPanel } from "./WmsPanel";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, approveJob: vi.fn() };
});

const exampleWms = (jobExample as Job).result!.wms;

beforeEach(() => {
  vi.mocked(api.approveJob).mockReset();
});

describe("WmsPanel", () => {
  it("예시의 '승인 대기'와 승인 입력을 보여 준다", () => {
    renderWithQuery(<WmsPanel jobId="job-7c1e" jobStatus="waiting_approval" wms={exampleWms} />);

    expect(screen.getByText("승인 대기")).toBeInTheDocument();
    expect(screen.getByLabelText("승인자")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "승인하고 WMS 등록" })).toBeDisabled();
  });

  it("승인자를 적고 누르면 approver 를 보낸다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.approveJob).mockResolvedValue({ wms: { status: "등록됨", wms_id: "WMS-0001" } });
    renderWithQuery(<WmsPanel jobId="job-7c1e" jobStatus="waiting_approval" wms={exampleWms} />);

    await user.type(screen.getByLabelText("승인자"), "  김담당 ");
    await user.click(screen.getByRole("button", { name: "승인하고 WMS 등록" }));

    await waitFor(() => expect(api.approveJob).toHaveBeenCalledWith("job-7c1e", "김담당"));
  });

  it("409 면 불일치가 남아 등록하지 않는다고 안내한다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.approveJob).mockRejectedValue(new api.ApiError(409, "불일치가 남아 있어 WMS에 등록할 수 없습니다"));
    renderWithQuery(<WmsPanel jobId="job-7c1e" jobStatus="waiting_approval" wms={exampleWms} />);

    await user.type(screen.getByLabelText("승인자"), "김담당");
    await user.click(screen.getByRole("button", { name: "승인하고 WMS 등록" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("WMS에 등록하지 못했습니다.");
    expect(alert).toHaveTextContent("원본을 확인해 판독 오류면 사유를 적고 승인해 주세요.");
    expect(alert).toHaveTextContent("서버: 불일치가 남아 있어 WMS에 등록할 수 없습니다");
  });

  it("다른 오류는 서버 문장만 보여 준다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.approveJob).mockRejectedValue(new api.ApiError(501, "아직 만들지 않은 경로입니다 (D3)"));
    renderWithQuery(<WmsPanel jobId="job-7c1e" jobStatus="waiting_approval" wms={exampleWms} />);

    await user.type(screen.getByLabelText("승인자"), "김담당");
    await user.click(screen.getByRole("button", { name: "승인하고 WMS 등록" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("아직 만들지 않은 경로입니다 (D3)");
    expect(alert).not.toHaveTextContent("WMS에 등록하지 못했습니다.");
  });

  it("등록됨이면 경로와 WMS 번호를 보여 주고 승인 입력은 없다", () => {
    renderWithQuery(
      <WmsPanel jobId="job-7c1e" jobStatus="done" wms={{ status: "등록됨", by: "auto", wms_id: "WMS-0042" }} />,
    );

    expect(screen.getByText("등록됨")).toBeInTheDocument();
    expect(screen.getByText("자동 등록")).toBeInTheDocument();
    expect(screen.getByText("WMS-0042")).toBeInTheDocument();
    expect(screen.queryByLabelText("승인자")).not.toBeInTheDocument();
  });

  it("사람이 승인해 등록한 작업은 검수자와 '검수 완료서 받기' 링크를 보인다 (X1 #258)", () => {
    renderWithQuery(
      <WmsPanel
        jobId="job-7c1e"
        jobStatus="done"
        wms={{ status: "등록됨", by: "human", wms_id: "WMS-0042", approver: "김담당", approved_at: "2026-11-21T09:30:12+09:00" }}
      />,
    );
    const link = screen.getByRole("link", { name: "검수 완료서 받기" });
    expect(link).toHaveAttribute("href", "/api/jobs/job-7c1e/certificate");
    expect(screen.getByText(/검수자 김담당/)).toBeInTheDocument();
    expect(screen.getByText(/2026-11-21 09:30/)).toBeInTheDocument();
  });

  it("자동 등록·승인 대기에는 검수 완료서 링크가 없다", () => {
    const { unmount } = renderWithQuery(
      <WmsPanel jobId="job-7c1e" jobStatus="done" wms={{ status: "등록됨", by: "auto", wms_id: "WMS-0042" }} />,
    );
    expect(screen.queryByRole("link", { name: "검수 완료서 받기" })).not.toBeInTheDocument();
    unmount();
    renderWithQuery(<WmsPanel jobId="job-7c1e" jobStatus="waiting_approval" wms={exampleWms} />);
    expect(screen.queryByRole("link", { name: "검수 완료서 받기" })).not.toBeInTheDocument();
  });

  it("승인 입력 곁에 이름이 검수 완료서에 찍힌다고 알린다", () => {
    renderWithQuery(<WmsPanel jobId="job-7c1e" jobStatus="waiting_approval" wms={exampleWms} />);
    expect(screen.getByText("입력한 이름이 검수 완료서에 검수자로 찍힙니다.")).toBeInTheDocument();
  });

  it("승인 대기인데 서버 wms 가 null 이면(배포 전·옛 작업) 승인 대기로 보고 승인 입력을 보인다 (FB01-b)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.approveJob).mockResolvedValue({ wms: { status: "등록됨", wms_id: "WMS-0007" } } as never);
    renderWithQuery(<WmsPanel jobId="job-7c1e" jobStatus="waiting_approval" wms={null} />);

    expect(screen.getByText("승인 대기")).toBeInTheDocument();
    expect(screen.queryByText("WMS 상태가 아직 없습니다.")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("승인자"), "김담당");
    await user.click(screen.getByRole("button", { name: "승인하고 WMS 등록" }));
    await waitFor(() => expect(api.approveJob).toHaveBeenCalledWith("job-7c1e", "김담당"));
  });

  it("wms 가 null 이어도 승인 대기가 아니면(끝남) 승인 입력은 없다", () => {
    renderWithQuery(<WmsPanel jobId="job-7c1e" jobStatus="done" wms={null} />);
    expect(screen.getByText("WMS 상태가 아직 없습니다.")).toBeInTheDocument();
    expect(screen.queryByLabelText("승인자")).not.toBeInTheDocument();
  });

  it("wms 가 null 인 승인 대기에서 불일치가 남아 409 면 같은 안내를 보인다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.approveJob).mockRejectedValue(new api.ApiError(409, "불일치가 남아 등록하지 않습니다"));
    renderWithQuery(<WmsPanel jobId="job-7c1e" jobStatus="waiting_approval" wms={null} />);
    await user.type(screen.getByLabelText("승인자"), "김담당");
    await user.click(screen.getByRole("button", { name: "승인하고 WMS 등록" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("WMS에 등록하지 못했습니다.");
  });

  it("불일치가 남으면 판독 오류 확인 체크와 사유를 채워야 승인할 수 있고, 사유를 함께 보낸다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.approveJob).mockResolvedValue({ wms: { status: "등록됨", wms_id: "WMS-0001" } });
    renderWithQuery(
      <WmsPanel jobId="job-7c1e" jobStatus="waiting_approval" wms={exampleWms} blocked="불일치 1건: 서류를 고쳐 다시 올리거나…" />,
    );
    const button = screen.getByRole("button", { name: "판독 오류로 승인하고 WMS 등록" });

    await user.type(screen.getByLabelText("승인자"), "김담당");
    expect(button).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "원본 서류를 직접 확인했고, 불일치는 판독 오류입니다" }));
    expect(button).toBeDisabled(); // 사유가 아직 없다
    await user.type(screen.getByLabelText("사유"), " 원본 송장 번호 같음 ");
    expect(button).toBeEnabled();
    await user.click(button);

    await waitFor(() => expect(api.approveJob).toHaveBeenCalledWith("job-7c1e", "김담당", "원본 송장 번호 같음"));
  });

  it("판독 오류로 넘겨 등록한 작업은 사유를 보인다", () => {
    renderWithQuery(
      <WmsPanel
        jobId="job-7c1e"
        jobStatus="done"
        wms={{ status: "등록됨", by: "human", wms_id: "WMS-0001", approver: "김담당", override_reason: "원본 송장 번호 같음" }}
      />,
    );
    expect(screen.getByText("불일치를 판독 오류로 확인해 승인 · 사유: 원본 송장 번호 같음")).toBeInTheDocument();
  });

  it("불일치가 없으면 판독 오류 입력을 보이지 않는다", () => {
    renderWithQuery(<WmsPanel jobId="job-7c1e" jobStatus="waiting_approval" wms={exampleWms} />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
