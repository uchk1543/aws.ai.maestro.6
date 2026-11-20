// 왼쪽 메뉴와 해시 주소
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { renderWithQuery } from "./test-utils";

describe("App", () => {
  it("첫 화면은 업로드, 메뉴로 AI chat 에 갔다가 돌아온다", async () => {
    const user = userEvent.setup();
    renderWithQuery(<App />);

    expect(screen.getByRole("heading", { name: "파일 업로드" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "AI chat" }));
    expect(window.location.hash).toBe("#/chat");
    expect(await screen.findByRole("heading", { name: "AI chat" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI chat" })).toHaveAttribute("aria-current", "page");

    await user.click(screen.getByRole("button", { name: "파일 업로드" }));
    expect(await screen.findByRole("heading", { name: "파일 업로드" })).toBeInTheDocument();
  });

  it("앱 바(모바일)에 앱 이름과 지금 화면 제목을 적는다", async () => {
    const user = userEvent.setup();
    const { container } = renderWithQuery(<App />);

    expect(container.querySelector(".appbar-name")).toHaveTextContent("통관 서류 검토");
    expect(container.querySelector(".appbar-title")).toHaveTextContent("파일 업로드");

    await user.click(screen.getByRole("button", { name: "AI chat" }));
    expect(container.querySelector(".appbar-title")).toHaveTextContent("AI chat");
  });

  it("모르는 주소는 업로드 화면", async () => {
    window.location.hash = "#/nothing";
    await act(async () => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    renderWithQuery(<App />);
    expect(screen.getByRole("heading", { name: "파일 업로드" })).toBeInTheDocument();
  });
});
