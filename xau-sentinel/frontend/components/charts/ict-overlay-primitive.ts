// Canvas drawing for the ICT overlay. lightweight-charts has no boxes, so this series primitive paints
// the boxes, lines and labels from lib/ict-drawing.ts. It sits behind the candles, as the source does.

import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import type { IctDrawing } from "@/lib/ict-drawing";

type Attached = SeriesAttachedParameter<Time>;

class IctRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly owner: IctOverlayPrimitive) {}

  draw(target: CanvasRenderingTarget2D): void {
    this.owner.paint(target);
  }
}

class IctPaneView implements IPrimitivePaneView {
  constructor(private readonly owner: IctOverlayPrimitive) {}

  zOrder() {
    return "bottom" as const;
  }

  renderer(): IPrimitivePaneRenderer {
    return new IctRenderer(this.owner);
  }
}

export class IctOverlayPrimitive implements ISeriesPrimitive<Time> {
  private drawing: IctDrawing = { boxes: [], lines: [], labels: [] };
  private chart: IChartApi | null = null;
  private series: ISeriesApi<"Candlestick"> | null = null;
  private requestUpdate: (() => void) | null = null;
  private readonly views = [new IctPaneView(this)];

  attached(param: Attached): void {
    this.chart = param.chart as unknown as IChartApi;
    this.series = param.series as unknown as ISeriesApi<"Candlestick">;
    this.requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  setDrawing(drawing: IctDrawing): void {
    this.drawing = drawing;
    this.requestUpdate?.();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views;
  }

  /** Time to x in media pixels. Times outside the visible range clamp to the chart edge. */
  private xOf(t: number, width: number): number {
    const ts = this.chart?.timeScale();
    if (!ts) return 0;
    const x = ts.timeToCoordinate(t as UTCTimestamp);
    if (x !== null) return x;
    const range = ts.getVisibleRange();
    if (!range) return 0;
    return Number(range.from) > t ? 0 : width;
  }

  private yOf(price: number): number | null {
    return this.series?.priceToCoordinate(price) ?? null;
  }

  paint(target: CanvasRenderingTarget2D): void {
    if (!this.series) return;
    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      const { width, height } = mediaSize;
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, width, height);
      ctx.clip();
      ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
      ctx.textBaseline = "middle";

      for (const b of this.drawing.boxes) {
        const yTop = this.yOf(b.top);
        const yBot = this.yOf(b.bottom);
        if (yTop === null || yBot === null) continue;
        const x1 = this.xOf(b.t1, width);
        const x2 = this.xOf(b.t2, width);
        const top = Math.min(yTop, yBot);
        const h = Math.abs(yBot - yTop);
        ctx.fillStyle = b.fill;
        ctx.fillRect(x1, top, x2 - x1, h);
        if (b.border !== "transparent") {
          ctx.strokeStyle = b.border;
          ctx.lineWidth = 1;
          ctx.setLineDash(b.dashed ? [4, 3] : []);
          ctx.strokeRect(x1, top, x2 - x1, h);
          ctx.setLineDash([]);
        }
        if (b.label) {
          ctx.fillStyle = b.label.color;
          ctx.textAlign = "left";
          ctx.fillText(b.label.text, x1 + 4, top + 9);
        }
      }

      for (const l of this.drawing.lines) {
        const y = this.yOf(l.price);
        if (y === null) continue;
        const x1 = this.xOf(l.t1, width);
        const x2 = this.xOf(l.t2, width);
        ctx.strokeStyle = l.color;
        ctx.lineWidth = 1;
        ctx.setLineDash(l.dashed ? [4, 3] : []);
        ctx.beginPath();
        ctx.moveTo(x1, y);
        ctx.lineTo(x2, y);
        ctx.stroke();
        ctx.setLineDash([]);
        if (l.label) {
          ctx.fillStyle = l.label.color;
          ctx.textAlign = l.label.align;
          ctx.fillText(l.label.text, l.label.align === "right" ? x2 - 4 : x1 + 4, y - 9);
        }
      }

      for (const lab of this.drawing.labels) {
        const y = this.yOf(lab.price);
        if (y === null) continue;
        const x = this.xOf(lab.t, width);
        ctx.fillStyle = lab.color;
        ctx.textAlign = "right";
        ctx.fillText(lab.text, x - 4, y - 9);
      }
      ctx.restore();
    });
  }
}
