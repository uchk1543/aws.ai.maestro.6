// G15 대시보드: 서버 숫자 그대로, 통계를 누르면 연관된 문서 분류 내역·AI chat 으로, 애니메이션 ON/OFF
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import statsDraft from "../fixtures/stats.draft.json";
import { renderWithQuery } from "../test-utils";
import type { StatsResponse } from "../types";
import { DashboardPage, FX_KEY, initialFx } from "./DashboardPage";

vi.mock("../api", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api")>();
  return { ...real, getStats: vi.fn() };
});

const stats = statsDraft as unknown as StatsResponse;

function hashParams() {
  const [path, query = ""] = decodeURIComponent(window.location.hash.replace(/^#/, "")).split("?");
  return { path, params: Object.fromEntries(new URLSearchParams(query)) };
}

beforeEach(() => {
  vi.mocked(api.getStats).mockReset().mockResolvedValue(stats);
  window.localStorage.removeItem(FX_KEY);
});

describe("DashboardPage", () => {
  it("지금 할 일 다섯 가지를 서버 숫자 그대로 보여 준다 (단순 보기)", async () => {
    window.localStorage.setItem(FX_KEY, "off");
    renderWithQuery(<DashboardPage />);

    const tiles = within(await screen.findByRole("list", { name: "지금 할 일" })).getAllByRole("button");
    expect(tiles.map((t) => t.getAttribute("aria-label"))).toEqual([
      "승인 대기 1건 보기",
      "불일치 남은 작업 1건 보기",
      "HS 고를 품목 1건 보기",
      "분류 못 한 서류 2건 보기",
      "통관 지연 화물 4건 보기",
    ]);
    expect(tiles[1]).toHaveClass("alert"); // 불일치가 남으면 빨강
    expect(screen.queryByText("부산항 통관 현황")).not.toBeInTheDocument();
  });

  it("통관 흐름 · 지연 화물 · 종류별 서류 · 자동 처리율 · 자주 걸린 오류를 보여 준다", async () => {
    window.localStorage.setItem(FX_KEY, "off");
    renderWithQuery(<DashboardPage />);

    expect(await screen.findByRole("button", { name: "심사 중 4건" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "반출 29건" })).toBeInTheDocument();
    expect(screen.getByText("SMLNCAN26003548")).toBeInTheDocument();
    expect(screen.getByText("8일째")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "분류 못 함 2장" })).toBeInTheDocument();
    expect(screen.getByText("끝난 작업 3건 중 2건이 사람 손 없이 WMS에 등록됐습니다")).toBeInTheDocument();
    expect(screen.getByText("67%")).toBeInTheDocument(); // 2/3 (서버 두 숫자의 비율만 그린다)
    expect(screen.getByRole("button", { name: /X-WT-01/ })).toHaveTextContent("1건");
  });

  it("서류 통계를 누르면 그 조건의 문서 분류 내역으로 간다", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(FX_KEY, "off");
    renderWithQuery(<DashboardPage />);

    await user.click(await screen.findByRole("button", { name: "불일치 남은 작업 1건 보기" }));
    expect(hashParams()).toEqual({ path: "/documents", params: { job_status: "waiting_approval", grade: "불일치" } });

    await user.click(screen.getByRole("button", { name: "HS 고를 품목 1건 보기" }));
    expect(hashParams().params).toEqual({ job_status: "waiting_approval", hs: "pending" });

    await user.click(screen.getByRole("button", { name: "분류 못 한 서류 2건 보기" }));
    expect(hashParams()).toEqual({ path: "/documents", params: { type: "unknown" } });

    await user.click(screen.getByRole("button", { name: /X-WT-01/ }));
    expect(hashParams().params).toEqual({ rule_id: "X-WT-01" });

    await user.click(screen.getByRole("button", { name: "포장명세서 3장" }));
    expect(hashParams().params).toEqual({ type: "packing_list" });
  });

  it("화물 통계를 누르면 AI chat 질문으로 간다", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(FX_KEY, "off");
    renderWithQuery(<DashboardPage />);

    await user.click(await screen.findByRole("button", { name: "통관 지연 화물 4건 보기" }));
    expect(hashParams()).toEqual({ path: "/chat", params: { q: "지금 통관이 늦어지고 있는 화물 전부 보여줘" } });

    await user.click(screen.getByRole("button", { name: "심사 중 4건" }));
    expect(hashParams().params).toEqual({ q: "심사 중 화물 전체 알려줘" });
  });

  it("오른쪽 위 ON/OFF 로 부산항 장면을 켜고 끄고, 고른 값을 기억한다", async () => {
    const user = userEvent.setup();
    renderWithQuery(<DashboardPage />);

    const toggle = screen.getByRole("button", { name: /애니메이션/ });
    expect(toggle).toHaveAttribute("aria-pressed", "true"); // 처음은 ON
    expect(await screen.findByText("부산항 통관 현황")).toBeInTheDocument();
    expect(await screen.findByText("확인할 일 7건이 들어와 있습니다")).toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(toggle).toHaveTextContent("애니메이션 OFF");
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
    expect(await screen.findByRole("alert")).toHaveTextContent("없는 경로입니다");
  });
});
