// G15 대시보드 + #252: 할 일은 작업 단위(next_action), 카드를 누르면 그 자리에 작업 목록, 줄을 누르면 작업 화면.
// AI chat 으로 질문을 자동으로 보내는 클릭은 없다. 옛 서버(새 칸 없음)에서는 예전 타일과 문서 분류 내역 이동.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import jobsDraft from "../fixtures/jobs.draft.json";
import statsDraft from "../fixtures/stats.draft.json";
import { renderWithQuery } from "../test-utils";
import type { JobListResponse, StatsResponse } from "../types";
import { DashboardPage, FX_KEY, hasNextCounts, initialFx, todoTotal } from "./DashboardPage";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, getStats: vi.fn(), getJobs: vi.fn() };
});

const stats = statsDraft as unknown as StatsResponse;
const jobs = jobsDraft as unknown as JobListResponse;
/** 옛 서버(#252 PR A 전): 다음 할 일별 칸·이름·조건 문장이 없다 */
const oldStats: StatsResponse = {
  ...stats,
  todo: {
    waiting_approval: 1,
    mismatch_jobs: 1,
    hs_pending: 1,
    unclassified: 2,
    delayed: 4,
  },
  auto: { finished: 3, auto: 2 },
  top_rules: [
    ...stats.top_rules.map(({ name, ...r }) => (void name, r)),
    { rule_id: "DOC-LATER", grade: "참고", count: 9, example: "선하증권은 아직 읽지 않습니다." },
  ],
};

function hashParams() {
  const [path, query = ""] = decodeURIComponent(window.location.hash.replace(/^#/, "")).split("?");
  return { path, params: Object.fromEntries(new URLSearchParams(query)) };
}

beforeEach(() => {
  vi.mocked(api.getStats).mockReset().mockResolvedValue(stats);
  vi.mocked(api.getJobs)
    .mockReset()
    .mockImplementation((kind) => Promise.resolve({ items: jobs.items.filter((j) => j.next_action.kind === kind) }));
  window.localStorage.setItem(FX_KEY, "off");
  window.location.hash = "#/dashboard";
});

describe("DashboardPage", () => {
  it("할 일 타일은 모두 작업 단위로, 다음 할 일마다 하나씩 (#252)", async () => {
    renderWithQuery(<DashboardPage />);

    const tiles = within(await screen.findByRole("list", { name: "지금 할 일" })).getAllByRole("button");
    expect(tiles.map((t) => t.getAttribute("aria-label"))).toEqual([
      "오류 서류 1건 보기",
      "HS 미작성 1건 보기",
      "미승인 서류 1건 보기",
      "미인식 서류 1건 보기",
      "처리 중 0건 보기",
    ]);
    expect(tiles[0]).toHaveClass("alert"); // 서류를 고쳐야 하는 작업이 있으면 빨강
    // 이름 아래 설명 (G18 #255)
    expect(tiles.map((t) => t.querySelector(".todo-hint")?.textContent)).toEqual([
      "불일치로 인해 서류 재업로드 필요",
      "작업자가 HS 확인하고 전송 필요",
      "서류 확인 후 승인 필요",
      "서류 재촬영 필요",
      "처리가 끝나지 않은 서류",
    ]);
    expect(tiles.every((t) => t.getAttribute("aria-expanded") === "false")).toBe(true);
  });

  it("카드를 누르면 그 자리에 작업 목록이 펼쳐지고, 줄을 누르면 작업 화면으로 간다", async () => {
    const user = userEvent.setup();
    renderWithQuery(<DashboardPage />);

    const tile = await screen.findByRole("button", { name: "HS 미작성 1건 보기" });
    await user.click(tile);
    expect(tile).toHaveAttribute("aria-expanded", "true");
    expect(hashParams()).toEqual({ path: "/dashboard", params: { open: "choose_hs" } }); // 뒤로 오면 다시 펼친다
    expect(api.getJobs).toHaveBeenCalledWith("choose_hs");

    const panel = await screen.findByRole("region", { name: "HS 미작성 작업 목록" });
    const row = await within(panel).findByRole("button", { name: /B\/L SMLNCAN26003548/ });
    expect(row).toHaveTextContent("샘플트레이딩코리아");
    expect(row).toHaveTextContent("HS 1개를 고르세요");

    await user.click(row);
    expect(hashParams().path).toBe("/jobs/job-1a2b");
  });

  it("같은 카드를 다시 누르거나 닫기를 누르면 목록이 닫힌다. 주소의 open 으로 펼친 채 시작한다", async () => {
    const user = userEvent.setup();
    renderWithQuery(<DashboardPage open="fix_docs" />);

    expect(await screen.findByRole("region", { name: "오류 서류 작업 목록" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "목록 닫기" }));
    expect(screen.queryByRole("region", { name: /작업 목록/ })).not.toBeInTheDocument();
    expect(hashParams()).toEqual({ path: "/dashboard", params: {} });

    await user.click(screen.getByRole("button", { name: "미승인 서류 1건 보기" }));
    expect(await screen.findByRole("region", { name: "미승인 서류 작업 목록" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "미승인 서류 1건 보기" }));
    expect(screen.queryByRole("region", { name: /작업 목록/ })).not.toBeInTheDocument();
  });

  it("작업 목록 경로가 아직 없으면(404) 문서 분류 내역으로 가는 길을 준다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getJobs).mockRejectedValue(new api.ApiError(404, "없는 경로입니다"));
    renderWithQuery(<DashboardPage open="fix_docs" />);

    await user.click(await screen.findByRole("button", { name: "문서 분류 내역에서 보기" }));
    expect(hashParams()).toEqual({ path: "/documents", params: { job_status: "waiting_approval", grade: "불일치" } });
  });

  it("AI chat 으로 질문을 자동으로 보내는 클릭이 없다: 통관 흐름은 누르지 않는다", async () => {
    renderWithQuery(<DashboardPage />);

    expect(await screen.findByLabelText("심사 중 4건")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "심사 중 4건" })).not.toBeInTheDocument();
    expect(screen.getByText("SMLNCAN26003548")).toBeInTheDocument(); // 지연 목록은 같은 화면에
    expect(screen.getByText("8일째")).toBeInTheDocument();
  });

  it("통관 지연 줄은 연결된 작업이 있으면 누르면 그 작업 화면으로 간다 (G18)", async () => {
    const user = userEvent.setup();
    renderWithQuery(<DashboardPage />);

    await user.click(await screen.findByRole("button", { name: "BL-2026-0001 작업 화면 열기" }));
    expect(hashParams().path).toBe("/jobs/job-7c1e");
    // 미리 넣은 가상 기록(작업 없음)은 누르는 줄이 아니다
    expect(screen.queryByRole("button", { name: "SMLNCAN26003548 작업 화면 열기" })).not.toBeInTheDocument();
  });

  it("자동 처리율은 종류별 서류 아래에, 분모를 바로 적고 조건을 붙인다. 오류는 짧은 이름을 크게", async () => {
    renderWithQuery(<DashboardPage />);
    // 순서: 종류별 서류 → 자동 처리율 → 자주 걸린 오류 (G18 #255)
    await screen.findByText("종류별 서류");
    const heads = [...document.querySelectorAll("#docs-title ~ .dash-sub")].map((h) => h.textContent);
    expect(heads).toEqual(["종류별 서류", "자동 처리율", "자주 걸린 오류"]);

    expect(await screen.findByText("처리를 마친 작업 3건(승인 대기 포함) 중 2건이 사람 손 없이 WMS에 등록됐습니다")).toBeInTheDocument();
    expect(screen.getByText("67%")).toBeInTheDocument();
    expect(screen.getByText(/모든 품목의 HS가 정해진 작업만/)).toBeInTheDocument();
    const rule = screen.getByRole("button", { name: /서류 간 총중량 불일치/ });
    expect(rule).toHaveTextContent("X-WT-01");
    expect(rule).not.toHaveTextContent("서류끼리 서류 전체 총중량이 같은지");
  });

  it("옛 서버면 예전 타일을 쓰고, 통관 지연은 AI chat 대신 같은 화면으로, '참고' 규칙은 뺀다", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getStats).mockResolvedValue(oldStats);
    renderWithQuery(<DashboardPage />);

    const tiles = within(await screen.findByRole("list", { name: "지금 할 일" })).getAllByRole("button");
    expect(tiles.map((t) => t.getAttribute("aria-label"))).toEqual([
      "승인 대기 1건 보기",
      "불일치 남은 작업 1건 보기",
      "HS 고를 품목 1건 보기",
      "분류 못 한 서류 2건 보기",
      "통관 지연 화물 4건 보기",
    ]);
    await user.click(tiles[4]);
    expect(hashParams().path).toBe("/dashboard");
    expect(screen.queryByText(/DOC-LATER/)).not.toBeInTheDocument();
    expect(screen.getByText(/불일치·확인 필요가 없고/)).toBeInTheDocument(); // 서버 문장이 없으면 화면 문장

    await user.click(tiles[1]);
    expect(hashParams()).toEqual({ path: "/documents", params: { job_status: "waiting_approval", grade: "불일치" } });
  });

  it("영상 위 '확인할 일'은 할 일 타일의 합이고, 통관 단계 칩은 없다 (G18)", async () => {
    window.localStorage.removeItem(FX_KEY);
    renderWithQuery(<DashboardPage />);

    expect(await screen.findByText("확인할 일 4건이 들어와 있습니다")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: /통관 단계/ })).not.toBeInTheDocument();
    expect(document.querySelector(".port-stages")).toBeNull();
  });

  it("todoTotal · hasNextCounts", () => {
    expect([hasNextCounts(stats), todoTotal(stats)]).toEqual([true, 4]);
    expect([hasNextCounts(oldStats), todoTotal(oldStats)]).toEqual([false, 1 + 2 + 4]);
  });

  it("오른쪽 위 ON/OFF 로 부산항 장면을 켜고 끄고, 고른 값을 기억한다", async () => {
    const user = userEvent.setup();
    window.localStorage.removeItem(FX_KEY);
    renderWithQuery(<DashboardPage />);

    const toggle = screen.getByRole("button", { name: /애니메이션/ });
    expect(toggle).toHaveAttribute("aria-pressed", "true"); // 처음은 ON
    expect(await screen.findByText("부산항 통관 현황")).toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText("부산항 통관 현황")).not.toBeInTheDocument();
    expect(window.localStorage.getItem(FX_KEY)).toBe("off");
  });

  it("움직임 줄이기 설정이면 처음부터 OFF", () => {
    const original = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia;
    try {
      expect(initialFx()).toBe(false);
    } finally {
      window.matchMedia = original;
    }
  });

  it("서버 오류 문장을 보여 준다", async () => {
    vi.mocked(api.getStats).mockRejectedValue(new api.ApiError(404, "없는 경로입니다"));
    renderWithQuery(<DashboardPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("없는 경로입니다"));
  });
});
