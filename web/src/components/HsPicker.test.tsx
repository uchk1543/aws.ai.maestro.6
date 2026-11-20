// G5 HS 선택: 후보 3개에서 골라 POST /api/jobs/{id}/hs 로 보낸다
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import jobExample from "../../../docs/examples/job_waiting_approval.json";
import * as api from "../api";
import { renderWithQuery } from "../test-utils";
import type { HSResult, Job } from "../types";
import { formatHs, HsPicker, lineTitle, manualHs } from "./HsPicker";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, chooseHs: vi.fn() };
});

const exampleHs = (jobExample as Job).result!.hs;

const needsHuman: HSResult = {
  line: 1,
  status: "사람 확인 필요",
  by: null,
  hs_code: null,
  candidates: [
    { hs: "8507600000", name: "리튬이온 축전지", reason: "품명 칸 LITHIUM-ION BATTERY PACK" },
    { hs: "8507800000", name: "그 밖의 축전지", reason: "용도 칸" },
    { hs: "8504409000", name: "정지형 변환기", reason: "품명 칸 PACK" },
  ],
};
const confirmed: HSResult = { line: 2, status: "자동 확정", by: "history", hs_code: "6109100000", candidates: [] };

beforeEach(() => {
  vi.mocked(api.chooseHs).mockReset();
});

describe("HsPicker", () => {
  it("예시의 '사람 확인 필요' 품목에 후보를 보여 준다", () => {
    renderWithQuery(<HsPicker jobId="job-7c1e" jobStatus="waiting_approval" results={exampleHs} />);

    expect(screen.getByText("사람 확인 필요")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /8507\.60-0000/ })).toBeInTheDocument();
    expect(screen.getByText("품명과 용도 칸 근거")).toBeInTheDocument();
  });

  it("확정된 품목은 HS 와 확정 경로를 보여 주고 후보를 고르지 않는다", () => {
    renderWithQuery(<HsPicker jobId="job-7c1e" jobStatus="waiting_approval" results={[confirmed]} />);

    expect(screen.getByText("6109.10-0000")).toBeInTheDocument();
    expect(screen.getByText("확정 이력")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("후보 하나를 고르고 확정하면 고른 행과 10자리 HS 를 보낸다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.chooseHs).mockResolvedValue({ declaration_draft: { fields: [], blank_fields: [], pdf_url: null } });
    renderWithQuery(<HsPicker jobId="job-7c1e" jobStatus="waiting_approval" results={[needsHuman, confirmed]} />);

    const submit = screen.getByRole("button", { name: "고른 HS 확정 (0/1)" });
    expect(submit).toBeDisabled();
    expect(screen.getAllByRole("radio")).toHaveLength(4); // 후보 3개 + 직접 입력

    await user.click(screen.getByRole("radio", { name: /8507\.80-0000/ }));
    await user.click(screen.getByRole("button", { name: "고른 HS 확정 (1/1)" }));

    await waitFor(() => expect(api.chooseHs).toHaveBeenCalledWith("job-7c1e", [{ line: 1, hs: "8507800000" }]));
  });

  it("서버가 거절하면 그 문장을 보여 준다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.chooseHs).mockRejectedValue(
      new api.ApiError(409, "이 작업에는 저장된 서류 기록이 없어 신고서 초안을 다시 채울 수 없습니다"),
    );
    renderWithQuery(<HsPicker jobId="job-7c1e" jobStatus="waiting_approval" results={[needsHuman]} />);

    await user.click(screen.getByRole("radio", { name: /8507\.60-0000/ }));
    await user.click(screen.getByRole("button", { name: /고른 HS 확정/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("저장된 서류 기록이 없어");
  });

  it("승인 대기가 아니면 고를 수 없다", () => {
    renderWithQuery(<HsPicker jobId="job-7c1e" jobStatus="done" results={[needsHuman]} />);

    expect(screen.getAllByRole("radio")[0]).toBeDisabled();
    expect(screen.getByRole("button", { name: /고른 HS 확정/ })).toBeDisabled();
    expect(screen.getByText("HS는 승인 대기 중인 작업에서만 고를 수 있습니다.")).toBeInTheDocument();
  });

  it("formatHs 는 10자리만 읽기 쉽게 바꾼다", () => {
    expect(formatHs("8507600000")).toBe("8507.60-0000");
    expect(formatHs("850760")).toBe("850760");
  });

  it("행 제목에 품명과 서류 HS 를 서버 값 그대로 보이고, 없으면 N행만 (FB07-c)", () => {
    const { unmount } = renderWithQuery(<HsPicker jobId="job-7c1e" jobStatus="waiting_approval" results={exampleHs} />);
    expect(screen.getByText("1행 · LITHIUM-ION BATTERY PACK (서류 HS 8507.60)")).toBeInTheDocument();
    unmount();
    renderWithQuery(<HsPicker jobId="job-7c1e" jobStatus="waiting_approval" results={[needsHuman]} />);
    expect(screen.getByText("1행")).toBeInTheDocument();
  });

  it("후보가 모두 틀리면 10자리를 직접 넣어 보낸다. 10자리가 아니면 보내기를 막는다 (FB07-c)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.chooseHs).mockResolvedValue({ declaration_draft: { fields: [], blank_fields: [], pdf_url: null } });
    renderWithQuery(<HsPicker jobId="job-7c1e" jobStatus="waiting_approval" results={[needsHuman]} />);

    const input = screen.getByLabelText("1행 HS 직접 입력");
    await user.type(input, "8507.60-90");
    expect(screen.getByRole("radio", { name: /직접 입력/ })).toBeChecked();
    expect(screen.getByText("숫자 10자리로 적어 주세요")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "고른 HS 확정 (1/1)" })).toBeDisabled();

    await user.type(input, "00");
    await user.click(screen.getByRole("button", { name: "고른 HS 확정 (1/1)" }));
    await waitFor(() => expect(api.chooseHs).toHaveBeenCalledWith("job-7c1e", [{ line: 1, hs: "8507609000" }]));
  });

  it("직접 넣은 코드를 서버가 400 으로 거절하면 그 문장을 그대로 보인다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.chooseHs).mockRejectedValue(new api.ApiError(400, "HS부호 표에 없는 코드입니다: 1234567890"));
    renderWithQuery(<HsPicker jobId="job-7c1e" jobStatus="waiting_approval" results={[needsHuman]} />);

    await user.type(screen.getByLabelText("1행 HS 직접 입력"), "1234567890");
    await user.click(screen.getByRole("button", { name: /고른 HS 확정/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("HS부호 표에 없는 코드입니다: 1234567890");
  });

  it("후보가 없어도 직접 입력 칸은 있다", () => {
    renderWithQuery(<HsPicker jobId="job-7c1e" jobStatus="waiting_approval" results={[{ ...needsHuman, candidates: [] }]} />);
    expect(screen.getByText(/후보가 없습니다/)).toBeInTheDocument();
    expect(screen.getByLabelText("1행 HS 직접 입력")).toBeInTheDocument();
  });

  it("manualHs · lineTitle", () => {
    expect([manualHs("8507609000"), manualHs("8507.60-9000"), manualHs("8507 60 9000"), manualHs("850760"), manualHs("85076090ab")]).toEqual([
      "8507609000",
      "8507609000",
      "8507609000",
      null,
      null,
    ]);
    expect(lineTitle({ ...needsHuman, item_name: "CHAIR", doc_hs_code: null })).toBe("1행 · CHAIR");
  });
});
