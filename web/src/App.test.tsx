// 메뉴와 해시 주소
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App, APP_NAME } from "./App";
import { renderWithQuery } from "./test-utils";

const UPLOAD_HEADING = "검토할 서류를 올려 주세요";

describe("App", () => {
  it("첫 화면은 업로드, 메뉴로 AI chat 에 갔다가 돌아온다", async () => {
    const user = userEvent.setup();
    renderWithQuery(<App />);

    expect(screen.getByRole("heading", { level: 1, name: UPLOAD_HEADING })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "파일 업로드" })).toHaveAttribute("aria-current", "page");

    await user.click(screen.getByRole("button", { name: "AI chat" }));
    expect(window.location.hash).toBe("#/chat");
    expect(await screen.findByRole("heading", { level: 1, name: "AI chat" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI chat" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "파일 업로드" })).not.toHaveAttribute("aria-current");

    await user.click(screen.getByRole("button", { name: "파일 업로드" }));
    expect(await screen.findByRole("heading", { level: 1, name: UPLOAD_HEADING })).toBeInTheDocument();
  });

  it("위에 앱 이름을 적고, 메뉴는 네 개(파일 업로드 · 작업 내역 · 대시보드 · AI chat)다", () => {
    renderWithQuery(<App />);

    expect(screen.getByText(APP_NAME)).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "메뉴" });
    expect(Array.from(nav.querySelectorAll("button")).map((b) => b.textContent)).toEqual(["파일 업로드", "작업 내역", "대시보드", "AI chat"]);
  });

  it("메뉴 '작업 내역'은 #/documents 를 연다", async () => {
    const user = userEvent.setup();
    renderWithQuery(<App />);

    await user.click(screen.getByRole("button", { name: "작업 내역" }));
    expect(window.location.hash).toBe("#/documents");
    expect(await screen.findByRole("heading", { level: 1, name: "작업 내역" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "작업 내역" })).toHaveAttribute("aria-current", "page");
  });

  it("모르는 주소는 업로드 화면", async () => {
    window.location.hash = "#/nothing";
    await act(async () => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    renderWithQuery(<App />);
    expect(screen.getByRole("heading", { level: 1, name: UPLOAD_HEADING })).toBeInTheDocument();
  });

  it("메뉴 '대시보드'는 #/dashboard 를 열고, 거르기 주소는 작업 내역에 넘긴다", async () => {
    const user = userEvent.setup();
    renderWithQuery(<App />);

    await user.click(screen.getByRole("button", { name: "대시보드" }));
    expect(window.location.hash).toBe("#/dashboard");
    expect(await screen.findByRole("heading", { level: 1, name: "대시보드" })).toBeInTheDocument();

    window.location.hash = "#/documents?grade=불일치";
    expect(await screen.findByLabelText("거르기")).toHaveTextContent("불일치가 남은 작업");
    expect(screen.getByRole("button", { name: "작업 내역" })).toHaveAttribute("aria-current", "page");
  });
});
