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
    expect(alert).toHaveTextContent("서류를 고쳐 다시 올려 주세요.");
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
});
