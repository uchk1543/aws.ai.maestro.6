// 테스트 준비: DOM 검사 도우미(toBeInTheDocument 등)와 테스트마다 화면 정리
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});
