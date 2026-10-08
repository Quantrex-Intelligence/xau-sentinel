// Turns the ICT (LuxAlgo) overlay data into drawing instructions for the chart primitive.
// Pure presentation: it only chooses shapes, colours and labels for values the API already returned.

import type { LuxalgoIctOverlay } from "./types";

export interface IctBox {
  t1: number;
  t2: number;
  top: number;
  bottom: number;
  fill: string;
  border: string;
  dashed: boolean;
  label?: { text: string; color: string };
}

export interface IctLine {
  t1: number;
  t2: number;
  price: number;
  color: string;
  dashed: boolean;
  label?: { text: string; color: string; align: "left" | "right" };
}

export interface IctLabel {
  t: number;
  price: number;
  text: string;
  color: string;
}

export interface IctDrawing {
  boxes: IctBox[];
  lines: IctLine[];
  labels: IctLabel[];
}

const BULL_FVG = { fill: "rgba(0, 230, 118, 0.14)", border: "rgba(0, 230, 118, 0.55)", text: "#00e676" };
const BEAR_FVG = { fill: "rgba(255, 82, 82, 0.14)", border: "rgba(255, 82, 82, 0.55)", text: "#ff5252" };
const BULL_OB = "#3e89fa";
const BEAR_OB = "#ff3131";
const BULL_OB_BREAK = "rgba(71, 133, 249, 0.14)";
const BEAR_OB_BREAK = "rgba(255, 49, 49, 0.14)";
const BUY_LIQ = { fill: "rgba(250, 69, 28, 0.16)", text: "#fa451c" };
const SELL_LIQ = { fill: "rgba(28, 228, 250, 0.16)", text: "#1ce4fa" };
const MSS_BULL = "#00e676";
const MSS_BEAR = "#ff5252";

export function buildIctDrawing(data: LuxalgoIctOverlay | null): IctDrawing {
  const out: IctDrawing = { boxes: [], lines: [], labels: [] };
  if (!data) return out;

  for (const f of data.fvg) {
    const c = f.side === "bullish" ? BULL_FVG : BEAR_FVG;
    out.boxes.push({
      t1: f.start_time, t2: f.end_time, top: f.top, bottom: f.bottom,
      fill: c.fill, border: c.border, dashed: true, label: { text: "FVG", color: c.text },
    });
  }

  for (const ob of data.order_blocks) {
    const bull = ob.side === "bullish";
    if (ob.breaker) {
      out.boxes.push({
        t1: ob.start_time, t2: ob.end_time, top: ob.top, bottom: ob.bottom,
        fill: bull ? BULL_OB_BREAK : BEAR_OB_BREAK, border: "transparent", dashed: false,
        label: { text: bull ? "+OB breaker" : "-OB breaker", color: bull ? BULL_OB : BEAR_OB },
      });
    } else {
      // Unbroken order blocks are a single line at the block's edge, as in the source script.
      const price = bull ? ob.bottom : ob.top;
      const color = bull ? BULL_OB : BEAR_OB;
      out.lines.push({
        t1: ob.start_time, t2: ob.end_time, price, color, dashed: false,
        label: { text: bull ? "+OB" : "-OB", color, align: "right" },
      });
    }
  }

  for (const q of data.liquidity) {
    const c = q.side === "buyside" ? BUY_LIQ : SELL_LIQ;
    const mid = (q.top + q.bottom) / 2;
    out.boxes.push({
      t1: q.start_time, t2: q.end_time, top: q.top, bottom: q.bottom,
      fill: c.fill, border: "transparent", dashed: false,
    });
    out.labels.push({
      t: q.end_time, price: mid, text: q.side === "buyside" ? "Buyside liquidity" : "Sellside liquidity",
      color: c.text,
    });
  }

  for (const s of data.structure) {
    const color = s.direction === "bullish" ? MSS_BULL : MSS_BEAR;
    out.lines.push({ t1: s.from_time, t2: s.time, price: s.level, color, dashed: false });
    out.labels.push({ t: s.time, price: s.level, text: s.kind, color });
  }

  return out;
}
