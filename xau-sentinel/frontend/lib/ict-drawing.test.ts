import { describe, expect, it } from "vitest";
import { buildIctDrawing } from "./ict-drawing";
import type { LuxalgoIctOverlay } from "./types";

const EMPTY: LuxalgoIctOverlay = {
  timeframe: "M5",
  bars: 300,
  note: "",
  fvg: [],
  order_blocks: [],
  liquidity: [],
  structure: [],
  last_bar_time: null,
};

describe("ICT drawing", () => {
  it("draws nothing when there is no overlay", () => {
    expect(buildIctDrawing(null)).toEqual({ boxes: [], lines: [], labels: [] });
  });

  it("draws an FVG as a dashed translucent box with its label", () => {
    const d = buildIctDrawing({
      ...EMPTY,
      fvg: [{ side: "bullish", top: 4170, bottom: 4165, start_time: 100, end_time: 900 }],
    });
    expect(d.boxes).toHaveLength(1);
    expect(d.boxes[0]).toMatchObject({ t1: 100, t2: 900, top: 4170, bottom: 4165, dashed: true });
    expect(d.boxes[0].label?.text).toBe("FVG");
  });

  it("draws an unbroken order block as a single line at its edge, not a box", () => {
    const bull = buildIctDrawing({
      ...EMPTY,
      order_blocks: [{ side: "bullish", top: 4130, bottom: 4120, start_time: 100, end_time: 900, breaker: false }],
    });
    expect(bull.boxes).toHaveLength(0);
    expect(bull.lines[0]).toMatchObject({ price: 4120, label: { text: "+OB" } });

    const bear = buildIctDrawing({
      ...EMPTY,
      order_blocks: [{ side: "bearish", top: 4130, bottom: 4120, start_time: 100, end_time: 900, breaker: false }],
    });
    expect(bear.lines[0]).toMatchObject({ price: 4130, label: { text: "-OB" } });
  });

  it("draws a broken order block (breaker) as a shaded box", () => {
    const d = buildIctDrawing({
      ...EMPTY,
      order_blocks: [{ side: "bullish", top: 4130, bottom: 4120, start_time: 100, end_time: 900, breaker: true }],
    });
    expect(d.lines).toHaveLength(0);
    expect(d.boxes[0].border).toBe("transparent");
    expect(d.boxes[0].label?.text).toBe("+OB breaker");
  });

  it("labels liquidity bands on the right with the side name", () => {
    const d = buildIctDrawing({
      ...EMPTY,
      liquidity: [{ side: "sellside", top: 4123, bottom: 4121, start_time: 100, end_time: 900 }],
    });
    expect(d.boxes[0].top).toBe(4123);
    expect(d.labels[0]).toMatchObject({ text: "Sellside liquidity", price: 4122 });
  });

  it("draws MSS and BOS as a line from the pivot to the shift bar, labelled by kind", () => {
    const d = buildIctDrawing({
      ...EMPTY,
      structure: [
        { kind: "MSS", direction: "bullish", level: 4140, from_time: 100, time: 400 },
        { kind: "BOS", direction: "bearish", level: 4132, from_time: 200, time: 500 },
      ],
    });
    expect(d.lines[0]).toMatchObject({ t1: 100, t2: 400, price: 4140 });
    expect(d.labels.map((l) => l.text)).toEqual(["MSS", "BOS"]);
  });
});
