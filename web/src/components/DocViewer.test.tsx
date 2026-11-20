// G16 서류 보기: 박스 여백, 돋보기 범위·배율, 박스를 누르면 확대가 열리고 닫힌다
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import draft from "../fixtures/documents.draft.json";
import { fileViewOf } from "../mockDocs";
import type { DocumentRecord, JobFileView } from "../types";
import { boxStyle, DocViewer, lensLayout, MARK_PAD, padBox, popSide, ZOOM, zoomRegion, type Box } from "./DocViewer";

const close = (a: number[], b: number[]) => a.forEach((v, i) => expect(v).toBeCloseTo(b[i], 6));

const file: JobFileView = fileViewOf((draft.items as DocumentRecord[]).find((d) => d.job_id === "job-7c1e")!);
const boxes: Box[] = file.marks
  .filter((m) => m.kind === "field")
  .map((m, i) => ({ id: `b${i}`, mark: m, tone: "soft", label: `읽은 값 · ${m.label}`, detail: [`칸 ${m.field}`] }));

describe("padBox · boxStyle (박스 여백)", () => {
  it("사방으로 max(박스 높이 25%, 쪽 0.4%) 만큼 넓힌다", () => {
    // 높이 0.04 → 0.01 씩
    close(padBox([0.1, 0.2, 0.3, 0.04]), [0.09, 0.19, 0.32, 0.06]);
    // 높이가 아주 작으면 쪽 크기의 0.4%
    close(padBox([0.5, 0.5, 0.1, 0.004]), [0.5 - MARK_PAD.pageRatio, 0.5 - MARK_PAD.pageRatio, 0.1 + 2 * MARK_PAD.pageRatio, 0.004 + 2 * MARK_PAD.pageRatio]);
  });

  it("가로 여백은 쪽 가로/세로 비로 바꿔 세로 여백과 같은 픽셀 길이가 되게 한다", () => {
    const [l] = padBox([0.1, 0.2, 0.3, 0.04], 0.5); // 세로로 긴 쪽: 가로 비율 여백이 두 배
    expect(l).toBeCloseTo(0.08, 6);
  });

  it("쪽 가장자리 밖으로 나가지 않게 자른다", () => {
    close(padBox([0, 0, 0.2, 0.04]), [0, 0, 0.21, 0.05]);
    close(padBox([0.9, 0.97, 0.2, 0.04]), [0.89, 0.96, 0.11, 0.04]);
    expect(boxStyle([0.1, 0.2, 0.3, 0.04])).toEqual({ left: "9.000%", top: "19.000%", width: "32.000%", height: "6.000%" });
  });
});

describe("zoomRegion · lensLayout (돋보기)", () => {
  it("넓힌 박스보다 넓게 잡아 앞뒤 맥락을 보이고, 박스가 범위 안에 다 들어간다", () => {
    const bbox: [number, number, number, number] = [0.4, 0.5, 0.2, 0.03];
    const [pl, pt, pw, ph] = padBox(bbox);
    const [l, t, w, h] = zoomRegion(bbox);
    expect(l).toBeLessThanOrEqual(pl);
    expect(t).toBeLessThanOrEqual(pt);
    expect(l + w).toBeGreaterThanOrEqual(pl + pw);
    expect(t + h).toBeGreaterThanOrEqual(pt + ph);
    expect(w).toBeGreaterThan(pw);
  });

  it("아주 작은 박스는 쪽 너비 minWidth 까지 키워 배율을 제한한다", () => {
    const [, , w] = zoomRegion([0.5, 0.5, 0.01, 0.005]);
    expect(w).toBeGreaterThanOrEqual(ZOOM.minWidth);
    expect(lensLayout([0.5, 0.5, 0.01, 0.005], zoomRegion([0.5, 0.5, 0.01, 0.005])).scale).toBeLessThanOrEqual(1 / ZOOM.minWidth);
  });

  it("가로/세로 비를 정한 범위 안으로 맞춘다", () => {
    for (const bbox of [[0.1, 0.1, 0.8, 0.01], [0.4, 0.4, 0.02, 0.2]] as [number, number, number, number][]) {
      const [, , w, h] = zoomRegion(bbox);
      const aspect = w / h;
      expect(aspect).toBeGreaterThanOrEqual(ZOOM.minAspect - 1e-9);
      expect(aspect).toBeLessThanOrEqual(ZOOM.maxAspect + 1e-9);
    }
  });

  it("쪽 가장자리에서는 안쪽으로 밀어 범위가 쪽 밖으로 나가지 않는다", () => {
    for (const bbox of [[0, 0, 0.1, 0.02], [0.95, 0.97, 0.05, 0.03]] as [number, number, number, number][]) {
      const [l, t, w, h] = zoomRegion(bbox);
      expect(l).toBeGreaterThanOrEqual(0);
      expect(t).toBeGreaterThanOrEqual(0);
      expect(l + w).toBeLessThanOrEqual(1 + 1e-9);
      expect(t + h).toBeLessThanOrEqual(1 + 1e-9);
    }
  });

  it("lensLayout 은 범위만 보이게 그림을 놓고 원래 인식 범위를 그 안의 % 로 둔다", () => {
    const { image, mark, scale } = lensLayout([0.3, 0.4, 0.1, 0.05], [0.2, 0.35, 0.4, 0.2]);
    expect(image).toEqual({ width: "250.000%", left: "-50.000%", top: "-175.000%" });
    expect(mark).toEqual({ left: "25.000%", top: "25.000%", width: "25.000%", height: "25.000%" });
    expect(scale).toBeCloseTo(2.5);
  });

  it("popSide 는 박스 위치로 상자 꼬리 방향을 고른다", () => {
    expect(popSide([0.1, 0.1, 0.2, 0.05])).toBe("pop-below pop-left");
    expect(popSide([0.7, 0.8, 0.2, 0.05])).toBe("pop-above pop-right");
  });
});

describe("DocViewer 돋보기", () => {
  it("박스를 누르면 그 부분의 확대 그림과 읽은 값이 열리고, X · Esc · 바깥 누르기로 닫힌다", async () => {
    const user = userEvent.setup();
    let active: string | null = null;
    const { rerender } = render(<DocViewer file={file} boxes={boxes} activeId={active} onSelect={(id) => (active = id)} />);
    expect(screen.queryByTestId("lens")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /1행 총중량/ }));
    rerender(<DocViewer file={file} boxes={boxes} activeId={active} onSelect={(id) => (active = id)} />);
    const pop = screen.getByRole("dialog", { name: /1행 총중량/ });
    expect(screen.getByRole("img", { name: "확대: 6,250.00 KGS" })).toHaveAttribute("src", file.pages[0].url);
    expect(pop).toHaveTextContent("6,250.00 KGS");

    await user.click(screen.getByRole("button", { name: "팝업 닫기" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    // 같은 박스를 다시 누르면 다시 열린다. Esc 로 닫는다
    await user.click(screen.getByRole("button", { name: /1행 총중량/ }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    // 바깥 누르기
    await user.click(screen.getByRole("button", { name: /1행 총중량/ }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("다른 박스를 누르면 확대가 바로 그 박스로 바뀐다", async () => {
    const user = userEvent.setup();
    let active: string | null = boxes[0].id;
    const view = () => <DocViewer file={file} boxes={boxes} activeId={active} onSelect={(id) => (active = id)} />;
    const { rerender } = render(view());
    const other = boxes[boxes.length - 1];
    await user.click(screen.getByRole("button", { name: `${other.label}: ${other.mark.text}` }));
    rerender(view());
    expect(screen.getByRole("dialog", { name: other.label })).toBeInTheDocument();
  });

  it("쪽 그림이 없으면(PDF 를 iframe 으로) 박스도 돋보기도 없다", () => {
    const pdf = { ...file, pages: [], url: "https://s3.test/a.pdf", content_type: "application/pdf" };
    render(<DocViewer file={pdf} boxes={boxes} activeId={boxes[0].id} />);
    expect(screen.getByTitle(`${file.file_name} 원본`)).toBeInTheDocument();
    expect(screen.queryByTestId("lens")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("모바일은 처음 강조한 박스의 돋보기를 닫힌 채로 시작하고, 박스를 누르면 연다", async () => {
    const user = userEvent.setup();
    const original = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia;
    try {
      let active: string | null = boxes[0].id;
      const view = () => <DocViewer file={file} boxes={boxes} activeId={active} onSelect={(id) => (active = id)} />;
      const { rerender } = render(view());
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: `${boxes[0].label}: ${boxes[0].mark.text}` }));
      rerender(view());
      expect(screen.getByRole("dialog", { name: boxes[0].label })).toBeInTheDocument();
    } finally {
      window.matchMedia = original;
    }
  });

  it("태블릿·PC 는 처음 강조한 박스의 돋보기를 바로 연다", () => {
    render(<DocViewer file={file} boxes={boxes} activeId={boxes[0].id} />);
    expect(screen.getByRole("dialog", { name: boxes[0].label })).toBeInTheDocument();
  });
});
