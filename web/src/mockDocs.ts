// 가짜 서류 그림 (npm run dev 전용, mock.ts 가 쓴다. 빌드에는 들어가지 않는다).
// 실제 서버는 서류를 쪽 그림으로 만들고 OCR 위치(bbox)를 준다(G11 제안). 가짜는 같은 배치표로 SVG 를 그리고
// 그 배치표에서 bbox 를 계산해, 박스가 글자 위에 정확히 겹치게 한다. 회사명·번호는 모두 가상 값이고 SAMPLE 을 찍는다.
import type { DocMark, DocType, DocumentRecord, JobFileView, MarkKind } from "./types";

const W = 1000;
const H = 1300;
const SIZE = 22;

interface Piece {
  x: number;
  y: number; // 글자 바닥선
  text: string;
  size?: number;
  bold?: boolean;
  anchor?: "start" | "middle";
  muted?: boolean;
  mark?: { kind: MarkKind; label: string; field?: string };
}

/** 글자 너비 어림값 (영문·숫자 기준, 한글은 넓게) */
function textWidth(text: string, size: number): number {
  let w = 0;
  for (const ch of text) w += /[가-힣]/.test(ch) ? size : size * 0.58;
  return w;
}

function boxOf(p: Piece): [number, number, number, number] {
  const size = p.size ?? SIZE;
  const w = textWidth(p.text, size);
  const left = p.anchor === "middle" ? p.x - w / 2 : p.x;
  const pad = 8;
  return [(left - pad) / W, (p.y - size - pad / 2) / H, (w + pad * 2) / W, (size * 1.3 + pad) / H];
}

function escapeXml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function svgOf(pieces: Piece[], extra = ""): string {
  const body = pieces
    .map((p) => {
      const size = p.size ?? SIZE;
      const attrs = [
        `x="${p.x}"`,
        `y="${p.y}"`,
        `font-size="${size}"`,
        p.bold ? `font-weight="700"` : "",
        p.anchor === "middle" ? `text-anchor="middle"` : "",
        `fill="${p.muted ? "#777" : "#1a1a1a"}"`,
      ].join(" ");
      return `<text ${attrs}>${escapeXml(p.text)}</text>`;
    })
    .join("");
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" ` +
    `font-family="Pretendard Variable, Malgun Gothic, Arial, sans-serif">` +
    `<rect width="${W}" height="${H}" fill="#fff"/>` +
    `<rect x="40" y="40" width="${W - 80}" height="${H - 80}" fill="none" stroke="#cfcfcf" stroke-width="2"/>` +
    `<text x="${W / 2}" y="${H / 2 + 120}" font-size="150" font-weight="700" fill="#000" fill-opacity="0.05" ` +
    `text-anchor="middle" transform="rotate(-28 ${W / 2} ${H / 2})">SAMPLE</text>` +
    extra +
    body +
    `</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function rule(y: number): string {
  return `<line x1="70" y1="${y}" x2="${W - 70}" y2="${y}" stroke="#bdbdbd" stroke-width="1.5"/>`;
}

/** 서류 종류별 배치표. 값은 레코드에서 가져온다. */
function layout(rec: DocumentRecord): { pieces: Piece[]; extra: string } {
  const docNo = rec.doc_no ?? "-";
  const consignee = rec.consignee ?? "-";
  // 예시 작업(job-7c1e)은 포장명세서 총중량이 다르게 찍혀 있다 (docs/examples/job_waiting_approval.json 의 불일치)
  const invoiceGross = "6,250.00 KGS";
  const packingGross = rec.job_id === "job-7c1e" ? "6,520.00 KGS" : "6,250.00 KGS";
  const head = (title: string, size = 40): Piece => ({
    x: W / 2,
    y: 130,
    text: title,
    size,
    bold: true,
    anchor: "middle",
    mark: { kind: "title", label: "제목" },
  });
  const label = (x: number, y: number, text: string): Piece => ({ x, y, text, size: 18, muted: true });

  switch (rec.doc_type) {
    case "commercial_invoice":
      return {
        extra: rule(390) + rule(425) + rule(560),
        pieces: [
          head("COMMERCIAL INVOICE"),
          label(80, 215, "Invoice No."),
          { x: 300, y: 215, text: docNo, mark: { kind: "field", label: "송장 번호", field: "doc_no" } },
          label(80, 265, "Consignee"),
          { x: 300, y: 265, text: consignee, mark: { kind: "field", label: "수하인", field: "consignee_name" } },
          label(80, 315, "Shipper"),
          { x: 300, y: 315, text: "SAMPLE EXPORT CO., LTD." },
          { x: 80, y: 415, text: "Description", size: 18, bold: true },
          { x: 420, y: 415, text: "Qty", size: 18, bold: true },
          { x: 530, y: 415, text: "Unit Price", size: 18, bold: true, mark: { kind: "feature", label: "특징 칸" } },
          { x: 680, y: 415, text: "Amount", size: 18, bold: true, mark: { kind: "feature", label: "특징 칸" } },
          { x: 820, y: 415, text: "G.W.", size: 18, bold: true },
          { x: 80, y: 470, text: "LITHIUM-ION BATTERY PACK", size: 18 },
          { x: 420, y: 470, text: "2,650 PCS", size: 18, mark: { kind: "field", label: "1행 수량", field: "items[0].qty" } },
          { x: 530, y: 470, text: "USD 41.20", size: 18 },
          { x: 680, y: 470, text: "USD 109,180.00", size: 18 },
          { x: 820, y: 470, text: invoiceGross, size: 18, mark: { kind: "field", label: "1행 총중량", field: "items[0].gross_kg" } },
          { x: 80, y: 600, text: "TOTAL", size: 18, bold: true },
          { x: 420, y: 600, text: "2,650 PCS", size: 18, mark: { kind: "field", label: "총수량", field: "total_qty" } },
          { x: 820, y: 600, text: invoiceGross, size: 18, mark: { kind: "field", label: "총중량", field: "total_gross_kg" } },
        ],
      };
    case "packing_list":
      return {
        extra: rule(390) + rule(425) + rule(560),
        pieces: [
          head("PACKING LIST"),
          label(80, 215, "Invoice No."),
          { x: 300, y: 215, text: docNo, mark: { kind: "field", label: "송장 번호", field: "doc_no" } },
          label(80, 265, "Consignee"),
          { x: 300, y: 265, text: consignee, mark: { kind: "field", label: "수하인", field: "consignee_name" } },
          { x: 80, y: 415, text: "Description", size: 18, bold: true },
          { x: 420, y: 415, text: "CTNS", size: 18, bold: true },
          { x: 530, y: 415, text: "N.W.", size: 18, bold: true, mark: { kind: "feature", label: "특징 칸" } },
          { x: 680, y: 415, text: "G.W.", size: 18, bold: true, mark: { kind: "feature", label: "특징 칸" } },
          { x: 830, y: 415, text: "Measurement", size: 18, bold: true, mark: { kind: "feature", label: "특징 칸" } },
          { x: 80, y: 470, text: "LITHIUM-ION BATTERY PACK", size: 18 },
          { x: 420, y: 470, text: "265", size: 18 },
          { x: 530, y: 470, text: "5,980.00 KGS", size: 18, mark: { kind: "field", label: "1행 순중량", field: "items[0].net_kg" } },
          { x: 680, y: 470, text: packingGross, size: 18, mark: { kind: "field", label: "1행 총중량", field: "items[0].gross_kg" } },
          { x: 830, y: 470, text: "18.4 CBM", size: 18 },
          { x: 80, y: 600, text: "TOTAL", size: 18, bold: true },
          { x: 680, y: 600, text: packingGross, size: 18, mark: { kind: "field", label: "총중량", field: "total_gross_kg" } },
        ],
      };
    case "bill_of_lading":
      return {
        extra: rule(560),
        pieces: [
          head("BILL OF LADING"),
          label(80, 215, "B/L No."),
          { x: 300, y: 215, text: docNo, mark: { kind: "field", label: "B/L 번호", field: "doc_no" } },
          { x: 80, y: 285, text: "Shipper", size: 18, bold: true, mark: { kind: "feature", label: "특징 칸" } },
          { x: 300, y: 285, text: "SAMPLE EXPORT CO., LTD." },
          { x: 80, y: 345, text: "Consignee", size: 18, bold: true, mark: { kind: "feature", label: "특징 칸" } },
          { x: 300, y: 345, text: consignee, mark: { kind: "field", label: "수하인", field: "consignee_name" } },
          { x: 80, y: 405, text: "Notify Party", size: 18, bold: true, mark: { kind: "feature", label: "특징 칸" } },
          { x: 300, y: 405, text: "SAME AS CONSIGNEE" },
          label(80, 475, "Vessel / Voyage"),
          { x: 300, y: 475, text: "SAMPLE STAR 026E" },
          label(80, 530, "Gross Weight"),
          { x: 300, y: 530, text: invoiceGross, mark: { kind: "field", label: "총중량", field: "total_gross_kg" } },
        ],
      };
    case "certificate_of_origin":
      return {
        extra: rule(390) + rule(425),
        pieces: [
          head("CERTIFICATE OF ORIGIN", 36),
          { x: W / 2, y: 180, text: "Form AK", size: 22, bold: true, anchor: "middle", mark: { kind: "feature", label: "서식 이름" } },
          label(80, 265, "Consignee"),
          { x: 300, y: 265, text: consignee, mark: { kind: "field", label: "수하인", field: "consignee_name" } },
          { x: 80, y: 415, text: "Description", size: 18, bold: true },
          { x: 470, y: 415, text: "HS Code", size: 18, bold: true },
          { x: 680, y: 415, text: "Origin Criterion", size: 18, bold: true, mark: { kind: "feature", label: "특징 칸" } },
          { x: 80, y: 470, text: "LITHIUM-ION BATTERY PACK", size: 18 },
          { x: 470, y: 470, text: "8507.60", size: 18, mark: { kind: "field", label: "1행 HS", field: "items[0].hs_code" } },
          { x: 680, y: 470, text: "PSR", size: 18 },
        ],
      };
    default:
      // 분류 못 함: 제목 자리가 가려진 스캔본
      return {
        extra:
          `<rect x="200" y="85" width="600" height="70" fill="#d9d9d9"/>` +
          [220, 290, 360, 430, 500, 570].map((y) => `<rect x="80" y="${y}" width="${520 + (y % 7) * 40}" height="16" fill="#e6e6e6"/>`).join(""),
        pieces: [{ x: W / 2, y: 200, text: "(제목이 보이지 않음)", size: 18, anchor: "middle", muted: true }],
      };
  }
}

/** 레코드 하나 → 서류 보기 한 건 (쪽 그림 1장 + 표시) */
export function fileViewOf(rec: DocumentRecord): JobFileView {
  const { pieces, extra } = layout(rec);
  const marks: DocMark[] = pieces
    .filter((p) => p.mark)
    .map((p) => ({ kind: p.mark!.kind, label: p.mark!.label, text: p.text, field: p.mark!.field ?? null, page: 1, bbox: boxOf(p) }));
  return {
    key: rec.key,
    file_name: rec.file_name,
    doc_type: rec.doc_type as DocType,
    classified_by: rec.classified_by,
    reason: rec.reason,
    pages: [{ url: svgOf(pieces, extra), width: W, height: H }],
    marks,
  };
}
