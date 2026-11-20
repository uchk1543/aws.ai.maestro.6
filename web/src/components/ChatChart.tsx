// #257 현황 그래프: 서버가 보낸 chart(값·축·제목은 서버 코드가 집계에서 채움)를 그대로 그린다. 화면은 계산하지 않는다.
// 막대·선은 SVG, 원은 SVG 부채꼴. 아래에 같은 값의 표를 늘 둔다 (접근성, 숫자 확인). 흑백 단계형: 짙기만 바꾼다.
import { useEffect, useRef, useState } from "react";
import type { Chart } from "../types";

const DEFAULT_W = 560;
const H = 220;
const PAD = { top: 16, right: 12, bottom: 40, left: 36 };
// 원 그래프 조각 짙기 (흑백 단계). 조각이 더 많으면 되풀이한다
const SHADES = [
  "#141414",
  "#4a4a4a",
  "#7a7a7a",
  "#a6a6a6",
  "#cfcfcf",
  "#e6e6e6",
];

/** 축 눈금: 0 부터 최댓값까지 정수 4칸 안팎 */
export function ticks(max: number): number[] {
  if (max <= 0) return [0];
  const step = Math.max(1, Math.ceil(max / 4));
  const out: number[] = [];
  for (let v = 0; v <= max + step - 1 && out.length < 6; v += step) out.push(v);
  return out;
}

function shortLabel(label: string, room: number): string {
  const chars = Math.max(2, Math.floor(room / 11));
  return label.length > chars ? `${label.slice(0, chars - 1)}…` : label;
}

/** 그릴 칸의 실제 너비(px). 비율로 줄이면 휴대폰에서 글자가 너무 작아져서, 너비에 맞춰 다시 그린다 */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(DEFAULT_W);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(240, Math.round(entry.contentRect.width))),
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function BarsOrLine({ chart }: { chart: Chart }) {
  const [ref, W] = useWidth();
  const points = chart.points;
  const axis = ticks(Math.max(...points.map((p) => p.value), 0));
  const top = axis[axis.length - 1] || 1;
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const slot = innerW / points.length;
  const y = (v: number) => PAD.top + innerH - (v / top) * innerH;
  const x = (i: number) => PAD.left + slot * i + slot / 2;
  const line = points
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`,
    )
    .join(" ");
  return (
    <div ref={ref}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width={W}
        height={H}
        className="chat-chart-svg"
        aria-hidden="true"
      >
        {axis.map((v) => (
          <g key={v}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(v)}
              y2={y(v)}
              className="chart-grid"
            />
            <text
              x={PAD.left - 6}
              y={y(v) + 4}
              textAnchor="end"
              className="chart-tick"
            >
              {v}
            </text>
          </g>
        ))}
        {chart.type === "bar" &&
          points.map((p, i) => {
            const bw = Math.min(48, slot * 0.6);
            return (
              <g key={p.label}>
                <rect
                  x={x(i) - bw / 2}
                  y={y(p.value)}
                  width={bw}
                  height={y(0) - y(p.value)}
                  className="chart-bar"
                />
                <text
                  x={x(i)}
                  y={y(p.value) - 5}
                  textAnchor="middle"
                  className="chart-value"
                >
                  {p.value}
                </text>
              </g>
            );
          })}
        {chart.type === "line" && (
          <>
            <path d={line} className="chart-line" />
            {points.map((p, i) => (
              <g key={p.label}>
                <circle cx={x(i)} cy={y(p.value)} r={4} className="chart-dot" />
                <text
                  x={x(i)}
                  y={y(p.value) - 9}
                  textAnchor="middle"
                  className="chart-value"
                >
                  {p.value}
                </text>
              </g>
            ))}
          </>
        )}
        {points.map((p, i) => (
          <text
            key={p.label}
            x={x(i)}
            y={H - PAD.bottom + 18}
            textAnchor="middle"
            className="chart-tick"
          >
            {shortLabel(p.label, slot)}
          </text>
        ))}
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={y(0)}
          y2={y(0)}
          className="chart-axis"
        />
      </svg>
    </div>
  );
}

/** 원 그래프 조각 경로. 한 조각이 전부면 원 하나 */
function slicePath(
  cx: number,
  cy: number,
  r: number,
  start: number,
  end: number,
): string {
  const a = (t: number) => [
    cx + r * Math.sin(t * 2 * Math.PI),
    cy - r * Math.cos(t * 2 * Math.PI),
  ];
  const [x1, y1] = a(start);
  const [x2, y2] = a(end);
  const large = end - start > 0.5 ? 1 : 0;
  return `M${cx},${cy} L${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 ${large} 1 ${x2.toFixed(2)},${y2.toFixed(2)} Z`;
}

function Pie({ chart }: { chart: Chart }) {
  const total = chart.points.reduce((s, p) => s + p.value, 0) || 1;
  let at = 0;
  return (
    <div className="chat-chart-pie">
      <svg
        viewBox="0 0 200 200"
        className="chat-chart-svg pie"
        aria-hidden="true"
      >
        {chart.points.length === 1 ? (
          <circle cx={100} cy={100} r={90} fill={SHADES[0]} />
        ) : (
          chart.points.map((p, i) => {
            const start = at;
            at += p.value / total;
            return (
              <path
                key={p.label}
                d={slicePath(100, 100, 90, start, at)}
                fill={SHADES[i % SHADES.length]}
                className="chart-slice"
              />
            );
          })
        )}
      </svg>
      <ul className="chart-legend" aria-hidden="true">
        {chart.points.map((p, i) => (
          <li key={p.label}>
            <span
              className="chart-swatch"
              style={{ background: SHADES[i % SHADES.length] }}
            />
            {p.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ChatChart({ chart }: { chart: Chart }) {
  if (chart.points.length === 0) return null;
  const kind = { bar: "막대그래프", line: "선 그래프", pie: "원 그래프" }[
    chart.type
  ];
  return (
    <figure className="chat-chart" aria-label={`${chart.title} ${kind}`}>
      <figcaption className="chat-chart-title">
        <strong>{chart.title}</strong>
        <span className="hint">{kind}</span>
      </figcaption>
      {chart.type === "pie" ? (
        <Pie chart={chart} />
      ) : (
        <BarsOrLine chart={chart} />
      )}
      <table className="cells chart-table">
        <thead>
          <tr>
            <th>{chart.x_label}</th>
            <th>{chart.y_label}</th>
          </tr>
        </thead>
        <tbody>
          {chart.points.map((p) => (
            <tr key={p.label}>
              <td>{p.label}</td>
              <td>{p.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
