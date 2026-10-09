"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  type IChartApi,
  type ISeriesApi,
  type IPriceLine,
  type UTCTimestamp,
  type MouseEventParams,
  createSeriesMarkers,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { RadioTower } from "lucide-react";
import { api } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { buildIctDrawing } from "@/lib/ict-drawing";
import { IctOverlayPrimitive } from "./ict-overlay-primitive";
import type {
  AnalysisV2Event,
  AnalysisV2Response,
  Candle,
  Liquidity,
  LuxalgoIctOverlay,
  StrategyEvaluation,
  Timeframe,
} from "@/lib/types";

const UP_COLOR = "#26a69a";
const DOWN_COLOR = "#ef5350";

// Chromium on Windows under-reports wheel delta for high-DPI displays; lightweight-charts corrects
// for it in its own time-axis wheel-zoom (confirmed directly in its source) so scroll speed matches
// other browsers. Computed once, same as the library's own module-level check.
const IS_WINDOWS_CHROME =
  typeof navigator !== "undefined" &&
  /Win/.test(navigator.platform) &&
  /Chrome|Chromium|Edg\//.test(navigator.userAgent) &&
  !/Firefox/.test(navigator.userAgent);

interface OhlcPoint {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
}

/** "08 Oct 14:35 UTC" -- unlike lib/format.ts's formatTime (time only), the OHLC legend spans
 * historical bars many days apart, so the date matters too. Exported for a direct unit test since
 * the chart canvas itself isn't practical to test. */
export function formatBarDateTime(time: UTCTimestamp): string {
  const d = new Date(time * 1000);
  return (
    d.toLocaleDateString(undefined, { day: "2-digit", month: "short", timeZone: "UTC" }) +
    " " +
    d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" }) +
    " UTC"
  );
}

/** True once the visible window's right edge is within WITHIN_BARS_OF_LIVE bars of the last loaded
 * bar -- the threshold the "Go to Live" button's visibility is based on. A small tolerance rather
 * than requiring exact alignment, matching TradingView's own non-flickery behavior at the live edge.
 * Exported for a direct unit test; the chart's own event handler just calls this. */
export const WITHIN_BARS_OF_LIVE = 2;
export function isAtLiveEdge(visibleRangeTo: number, totalBars: number): boolean {
  return visibleRangeTo >= totalBars - WITHIN_BARS_OF_LIVE;
}

/** Imperative actions ChartControls (a sibling, not a parent/child of the chart) triggers on it --
 * the standard React pattern for one component to drive another it doesn't render directly. */
export interface ChartHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  resetView: () => void;
}

const LEVEL_COLORS: Record<string, string> = {
  "Previous Day High": "#e06c75", "Previous Day Low": "#e06c75",
  "Asian High": "#d19a66", "Asian Low": "#d19a66",
  "London High": "#56b6c2", "London Low": "#56b6c2",
  "VWAP": "#abb2bf",
};

/** Levels the Market chart draws: previous day, the Asian and London session extremes, and VWAP. */
const CHART_LEVELS = ["Previous Day High", "Previous Day Low", "Asian High", "Asian Low", "London High", "London Low", "VWAP"];

/** Active key areas drawn on the chart. The nearest few to price, so the chart stays readable. */
const MAX_AREA_LINES = 4;

const AREA_COLORS: Record<string, string> = { RESISTANCE: "#e06c75", SUPPORT: "#98c379" };

const STRUCTURE_STYLE: Record<string, { shape: "circle" | "square"; text: string; color: string }> = {
  MSS: { shape: "circle", text: "MSS", color: "#e5c07b" },
  BOS: { shape: "square", text: "BOS", color: "#abb2bf" },
  DISPLACEMENT: { shape: "square", text: "DSP", color: "#61afef" },
};

export interface ChartOverlayToggles {
  /** Previous day, session and VWAP levels. */
  zones: boolean;
  liquidity: boolean;
  /** Structure shifts, BOS and displacement from the V2 events (M5 only). */
  structure: boolean;
  /** Nearest active key areas from the V2 analysis. */
  areas: boolean;
  /** A+ entry, stop and target from the current evaluation. */
  setup: boolean;
  /** ICT (LuxAlgo) reimplementation: FVG, order blocks, liquidity and MSS/BOS. Off-chart tool, not validated. */
  ict: boolean;
}

export const CandlestickChart = forwardRef<ChartHandle, {
  timeframe: Timeframe;
  zones: Record<string, number>;
  liquidity: Liquidity;
  analysis: AnalysisV2Response | null;
  aplus: StrategyEvaluation | null;
  latestCandle: Candle | null;
  overlays: ChartOverlayToggles;
  /** TradingView's own "lock scale" behavior: when true, the right price axis stops auto-fitting
   * to whatever candles are currently visible as you zoom/pan time, so the price axis only moves
   * when dragged by hand. When false (the default), it auto-scales on every zoom/pan, same as
   * TradingView's own default. */
  priceScaleLocked: boolean;
  /** Called by the imperative resetView() handle so a full reset also clears the scale lock, not
   * just the time range -- priceScaleLocked is lifted state in MarketPage, so this component can't
   * clear it on its own. */
  onResetPriceScale: () => void;
  /** Called when the user manually rescales price (wheel over the price axis) so the "Auto scale"
   * toggle's lifted state reflects it -- without this the button would keep claiming "auto" right
   * after a manual zoom locked it. */
  onPriceScaleManualDrag: () => void;
}>(function CandlestickChart(
  { timeframe, zones, liquidity, analysis, aplus, latestCandle, overlays, priceScaleLocked, onResetPriceScale, onPriceScaleManualDrag },
  handleRef,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  // lightweight-charts logs "Object is disposed" via its own internal
  // console.error (it doesn't throw it back to the caller), so wrapping
  // calls in try/catch can't suppress it — the only real fix is to never
  // call a chart/series method once disposal has started. Every other
  // effect below checks this before touching chartRef/seriesRef.
  const disposedRef = useRef(false);
  const ictRef = useRef<IctOverlayPrimitive | null>(null);
  // Mirrors the latest onPriceScaleManualDrag prop for the chart-lifecycle effect's wheel listener
  // below, which mounts once ([] deps) and would otherwise close over a stale callback.
  const onPriceScaleManualDragRef = useRef(onPriceScaleManualDrag);
  onPriceScaleManualDragRef.current = onPriceScaleManualDrag;
  // The most recently known bar (from the last setData/update) and the current total bar count --
  // feed the OHLC legend's "nothing hovered" fallback and the live-edge detection below. Refs, not
  // state: read during render/event callbacks, never need to themselves trigger a re-render.
  const latestBarRef = useRef<OhlcPoint | null>(null);
  const totalBarsRef = useRef(0);
  // True once setData() has loaded the current timeframe's history. Guards the live-update effect
  // below: the WS snapshot's first tick typically arrives well before the REST history fetch
  // resolves (confirmed directly -- the history endpoint alone can take several seconds), and
  // calling series.update() on an otherwise-empty series seeds it with a single bar, rendering as
  // a near-empty, stuck-looking view until the history finally loads and replaces it.
  const historyLoadedRef = useRef(false);
  const [hoveredBar, setHoveredBar] = useState<OhlcPoint | null>(null);
  const [atLiveEdge, setAtLiveEdge] = useState(true);
  // Tracks which timeframe the last fetch outcome belongs to, so "loading"
  // is derived (true whenever the current `timeframe` hasn't resolved yet)
  // instead of set synchronously at the top of the fetch effect.
  const [fetchResult, setFetchResult] = useState<{ timeframe: Timeframe; error: string | null } | null>(null);
  const loading = fetchResult?.timeframe !== timeframe;
  const error = fetchResult?.timeframe === timeframe ? fetchResult.error : null;

  // ICT (LuxAlgo) overlay: fetched for the current timeframe while the toggle is on, refreshed every 30 s.
  const [ictState, setIctState] = useState<{ timeframe: Timeframe; data: LuxalgoIctOverlay | null; error: string | null } | null>(null);
  useEffect(() => {
    if (!overlays.ict) return;
    let cancelled = false;
    const load = () =>
      api
        .luxalgoIct(timeframe, 300)
        .then((data) => !cancelled && setIctState({ timeframe, data, error: null }))
        .catch((err) => !cancelled && setIctState({ timeframe, data: null, error: err.message }));
    load();
    const id = setInterval(load, 30000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [timeframe, overlays.ict]);
  const ictData = overlays.ict && ictState?.timeframe === timeframe ? ictState.data : null;

  // Chart lifecycle: created once, disposed on unmount.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    disposedRef.current = false;
    const chart = createChart(container, {
      layout: { background: { color: "#131722" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#242832" }, horzLines: { color: "#242832" } },
      rightPriceScale: { borderColor: "#242832" },
      // maxBarSpacing defaults to 0 (no limit): confirmed directly that zooming in with no cap
      // eventually makes a single candle wider than the whole viewport, landing on an empty,
      // stuck-looking view with no candles in frame and panning barely able to recover it --
      // exactly the "can't zoom freely, gets stuck" symptom. TradingView caps how far you can zoom
      // in for the same reason; 80px/candle is generous (still much wider than this chart's normal
      // ~6px default) while keeping several candles on screen at maximum zoom.
      timeScale: { borderColor: "#242832", timeVisible: true, secondsVisible: false, maxBarSpacing: 80 },
      crosshair: { mode: 0 },
      autoSize: true,
      // Every other interaction knob (wheel zoom, drag-to-pan, pinch, axis-drag rescale) already
      // defaults to the same TradingView-like behavior this library ships with -- the one gap is
      // kinetic scroll on mouse, which defaults to off, so a mouse drag-pan stopped dead on release
      // instead of gliding (the MT5-like feel being asked to go away).
      kineticScroll: { touch: true, mouse: true },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP_COLOR, downColor: DOWN_COLOR,
      wickUpColor: UP_COLOR, wickDownColor: DOWN_COLOR,
      borderVisible: false,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    const ict = new IctOverlayPrimitive();
    series.attachPrimitive(ict);
    ictRef.current = ict;

    // OHLC legend: reads the hovered bar straight from the event, the same data the series itself
    // was given -- never recomputed. param.time is undefined when the cursor leaves the chart (or
    // hovers empty space before/after the data), at which point the render falls back to
    // latestBarRef so the legend is never blank, matching TradingView's own "shows latest when not
    // hovering" convention.
    const onCrosshairMove = (param: MouseEventParams<Time>) => {
      if (!param.time) {
        setHoveredBar(null);
        return;
      }
      const bar = param.seriesData.get(series);
      if (!bar || !("open" in bar)) {
        setHoveredBar(null);
        return;
      }
      setHoveredBar({ time: param.time as UTCTimestamp, open: bar.open, high: bar.high, low: bar.low, close: bar.close });
    };
    chart.subscribeCrosshairMove(onCrosshairMove);

    // "Go to Live": tracks whether the visible window's right edge is near the last loaded bar.
    // Within 2 bars counts as "at the edge" too, matching TradingView's own non-flickery threshold
    // rather than requiring pixel-perfect alignment with the very last bar.
    const onVisibleRangeChange = () => {
      const range = chart.timeScale().getVisibleLogicalRange();
      if (!range) return;
      setAtLiveEdge(isAtLiveEdge(range.to, totalBarsRef.current));
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onVisibleRangeChange);

    // The library's own wheel-zoom listener is bound to its outer wrapper element (confirmed
    // directly in its source), which spans the price axis too, and it always zooms time regardless
    // of cursor position -- scrolling over the price axis still moves X, never Y. There's no option
    // to change this, so a capture-phase listener here intercepts wheel events specifically over the
    // price axis and zooms price instead, before the library's own bubble-phase listener ever sees
    // the event (stopPropagation during capture prevents it from reaching that listener at all).
    // Anywhere else, this does nothing and the library's default time-zoom runs exactly as before.
    const onWheel = (event: WheelEvent) => {
      if (disposedRef.current) return;
      const priceScale = chart.priceScale("right");
      const axisWidth = priceScale.width();
      if (axisWidth <= 0) return;
      const rect = container.getBoundingClientRect();
      const localX = event.clientX - rect.left;
      if (localX < rect.width - axisWidth) return;
      event.preventDefault();
      event.stopPropagation();
      const range = priceScale.getVisibleRange();
      if (!range) return;

      // Same formula the library uses for its own time-axis wheel-zoom (_private__onMousewheel /
      // TimeScale._internal_zoom), mirrored onto price: a proportional step scaled by actual scroll
      // magnitude, not a fixed factor per event. A fixed factor per tick ignored deltaY entirely, so
      // a slow trackpad scroll (many small-delta events) jumped by the same amount as a hard mouse
      // click each event -- this instead feels identical in speed to the built-in horizontal zoom.
      let speedAdjustment = 1;
      if (event.deltaMode === event.DOM_DELTA_PAGE) speedAdjustment = 120;
      else if (event.deltaMode === event.DOM_DELTA_LINE) speedAdjustment = 32;
      else if (IS_WINDOWS_CHROME) speedAdjustment = 1 / window.devicePixelRatio;
      const adjustedDeltaY = -(speedAdjustment * event.deltaY) / 100;
      const zoomScale = Math.sign(adjustedDeltaY) * Math.min(1, Math.abs(adjustedDeltaY));
      if (zoomScale === 0) return;

      const cursorPrice = series.coordinateToPrice(event.clientY - rect.top) ?? (range.from + range.to) / 2;
      const span = range.to - range.from;
      const newSpan = span / (1 + zoomScale / 10);
      const ratioBelow = (cursorPrice - range.from) / span;
      priceScale.applyOptions({ autoScale: false });
      priceScale.setVisibleRange({
        from: cursorPrice - ratioBelow * newSpan,
        to: cursorPrice + (1 - ratioBelow) * newSpan,
      });
      onPriceScaleManualDragRef.current();
    };
    container.addEventListener("wheel", onWheel, { capture: true, passive: false });

    return () => {
      disposedRef.current = true;
      chart.unsubscribeCrosshairMove(onCrosshairMove);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onVisibleRangeChange);
      container.removeEventListener("wheel", onWheel, { capture: true });
      ictRef.current = null;
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Full history reload on timeframe switch.
  useEffect(() => {
    let cancelled = false;
    historyLoadedRef.current = false;
    api
      .candles(timeframe, 300)
      .then((candles) => {
        if (cancelled || disposedRef.current || !seriesRef.current) return;
        const mapped: OhlcPoint[] = candles.map((c) => ({
          time: c.time as UTCTimestamp,
          open: c.open, high: c.high, low: c.low, close: c.close,
        }));
        seriesRef.current.setData(mapped);
        totalBarsRef.current = mapped.length;
        latestBarRef.current = mapped[mapped.length - 1] ?? null;
        historyLoadedRef.current = true;
        chartRef.current?.timeScale().fitContent();
        setAtLiveEdge(true); // fitContent always lands on the live edge
        if (!cancelled) setFetchResult({ timeframe, error: null });
      })
      .catch((err) => !cancelled && setFetchResult({ timeframe, error: err.message }));
    return () => {
      cancelled = true;
    };
  }, [timeframe]);

  // TradingView's own scale-lock toggle: freezes the right price axis's current range instead of
  // auto-fitting it to whatever candles are visible on every zoom/pan.
  useEffect(() => {
    if (disposedRef.current || !chartRef.current) return;
    chartRef.current.priceScale("right").applyOptions({ autoScale: !priceScaleLocked });
  }, [priceScaleLocked]);

  // Incremental update from the live WS snapshot's latest M5 candle — no full rebuild. Deliberately
  // never touches the time scale (no fitContent/scrollToRealTime here): a user who has scrolled
  // back into history keeps their place exactly, even while this keeps the underlying data current
  // in the background -- update() only ever repaints the bar at its own time, it doesn't move what
  // the user is currently looking at.
  useEffect(() => {
    if (timeframe !== "M5" || !latestCandle || disposedRef.current || !seriesRef.current || !historyLoadedRef.current) return;
    const bar: OhlcPoint = {
      time: latestCandle.time as UTCTimestamp,
      open: latestCandle.open, high: latestCandle.high,
      low: latestCandle.low, close: latestCandle.close,
    };
    seriesRef.current.update(bar);
    if (bar.time !== latestBarRef.current?.time) totalBarsRef.current += 1; // a genuinely new bar, not a repaint of the forming one
    latestBarRef.current = bar;
  }, [latestCandle, timeframe]);

  // Level price lines (previous day, sessions, VWAP).
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || disposedRef.current) return;
    const lines = (overlays.zones ? Object.keys(zones) : []).filter((name) => CHART_LEVELS.includes(name));
    const created = lines.map((name) =>
      series.createPriceLine({
        price: zones[name],
        color: LEVEL_COLORS[name] ?? "#abb2bf",
        lineWidth: 1,
        lineStyle: 2,
        title: name,
      })
    );
    // The chart-lifecycle effect's cleanup can run before this one and
    // dispose the series first — guard on disposedRef rather than
    // try/catch, since the library logs disposal internally via
    // console.error instead of throwing back to the caller.
    return () => {
      if (disposedRef.current) return;
      created.forEach((l) => series.removePriceLine(l));
    };
  }, [zones, overlays.zones]);

  // Nearest active key areas, as a low and a high line each.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || disposedRef.current || !overlays.areas || !analysis) return;
    const areas = [...analysis.interpretation.key_areas]
      .sort((a, b) => Math.abs(a.distance_atr ?? 1e9) - Math.abs(b.distance_atr ?? 1e9))
      .slice(0, MAX_AREA_LINES);
    const created: IPriceLine[] = [];
    areas.forEach((a, i) => {
      const color = AREA_COLORS[a.side] ?? "#abb2bf";
      created.push(series.createPriceLine({ price: a.low, color, lineWidth: 1, lineStyle: 1, title: "" }));
      created.push(series.createPriceLine({ price: a.high, color, lineWidth: 1, lineStyle: 1, title: i === 0 ? "Area" : "" }));
    });
    return () => {
      if (disposedRef.current) return;
      created.forEach((l) => series.removePriceLine(l));
    };
  }, [analysis, overlays.areas]);

  // A+ entry, stop and target from the current evaluation (shown only once a candidate exists).
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || disposedRef.current || !overlays.setup || !aplus || aplus.direction === null) return;
    const created: IPriceLine[] = [];
    if (aplus.stop_loss !== null)
      created.push(series.createPriceLine({ price: aplus.stop_loss, color: "#ef5350", lineWidth: 2, lineStyle: 0, title: "SL" }));
    if (aplus.target !== null)
      created.push(series.createPriceLine({ price: aplus.target, color: "#26a69a", lineWidth: 2, lineStyle: 0, title: "TP" }));
    if (aplus.entry !== null)
      created.push(series.createPriceLine({ price: aplus.entry, color: "#61afef", lineWidth: 1, lineStyle: 3, title: "Entry" }));
    return () => {
      if (disposedRef.current) return;
      created.forEach((l) => series.removePriceLine(l));
    };
  }, [aplus, overlays.setup]);

  // ICT (LuxAlgo) overlay: boxes, lines and labels, painted by the series primitive.
  useEffect(() => {
    ictRef.current?.setDrawing(buildIctDrawing(ictData));
  }, [ictData]);

  // Markers: liquidity sweeps and equal levels, plus structure events on M5.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || disposedRef.current) return;
    // No text labels on sweeps or equal levels — with several events clustered
    // close together on M5 the labels overlapped into an unreadable pile.
    const liquidityMarkers: SeriesMarker<Time>[] = overlays.liquidity
      ? [
          ...liquidity.sweeps
            .filter((s) => s.time !== null)
            .map((s) => ({
              time: s.time as Time,
              position: (s.kind === "sweep_high" ? "aboveBar" : "belowBar") as "aboveBar" | "belowBar",
              color: s.kind === "sweep_high" ? "#ef5350" : "#26a69a",
              shape: (s.kind === "sweep_high" ? "arrowDown" : "arrowUp") as "arrowDown" | "arrowUp",
            })),
          ...liquidity.equal_levels
            .filter((e) => e.time !== null)
            .map((e) => ({
              time: e.time as Time,
              position: (e.kind === "equal_high" ? "aboveBar" : "belowBar") as "aboveBar" | "belowBar",
              color: "#e0a339",
              shape: "circle" as const,
            })),
        ]
      : [];
    const structureMarkers: SeriesMarker<Time>[] =
      overlays.structure && timeframe === "M5" && analysis
        ? analysis.events
            .filter((e) => e.kind in STRUCTURE_STYLE)
            .map((e: AnalysisV2Event) => {
              const style = STRUCTURE_STYLE[e.kind];
              const bullish = e.direction === "bullish";
              return {
                time: Math.floor(Date.parse(e.time_utc) / 1000) as Time,
                position: (bullish ? "belowBar" : "aboveBar") as "aboveBar" | "belowBar",
                color: style.color,
                shape: style.shape,
                text: style.text,
              };
            })
        : [];
    const markers = [...liquidityMarkers, ...structureMarkers].sort((a, b) => (a.time as number) - (b.time as number));
    const plugin = createSeriesMarkers(series, markers);
    return () => {
      if (disposedRef.current) return;
      plugin.detach();
    };
  }, [liquidity, overlays.liquidity, overlays.structure, analysis, timeframe]);

  // Zoom in/out/reset for ChartControls (a sibling, not a wrapper) to call. getVisibleLogicalRange()/
  // setVisibleLogicalRange() is the standard manual-zoom-button pattern for this library -- there is
  // no direct zoomIn()/zoomOut() method, so this scales the current range around its own center.
  useImperativeHandle(handleRef, () => ({
    zoomIn: () => zoomByFactor(0.7),
    zoomOut: () => zoomByFactor(1 / 0.7),
    resetView: () => {
      if (disposedRef.current || !chartRef.current) return;
      chartRef.current.timeScale().fitContent();
      onResetPriceScale();
    },
  }), [onResetPriceScale]);

  function zoomByFactor(factor: number) {
    if (disposedRef.current || !chartRef.current) return;
    const ts = chartRef.current.timeScale();
    const range = ts.getVisibleLogicalRange();
    if (!range) return;
    const center = (range.from + range.to) / 2;
    const halfWidth = ((range.to - range.from) * factor) / 2;
    ts.setVisibleLogicalRange({ from: center - halfWidth, to: center + halfWidth });
  }

  const displayBar = hoveredBar ?? latestBarRef.current;
  const bullish = displayBar ? displayBar.close >= displayBar.open : true;

  return (
    <div className="relative w-full h-full min-h-[420px]">
      <div ref={containerRef} className="absolute inset-0" />

      {displayBar && (
        <div className="absolute top-2 left-2 z-10 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs font-mono bg-card/70 rounded px-2 py-1 pointer-events-none">
          <span className={bullish ? "text-bullish" : "text-bearish"}>
            O {formatPrice(displayBar.open)} H {formatPrice(displayBar.high)} L {formatPrice(displayBar.low)} C {formatPrice(displayBar.close)}
          </span>
          <span className="text-muted-foreground">{formatBarDateTime(displayBar.time)}</span>
        </div>
      )}

      {!atLiveEdge && timeframe === "M5" && (
        <button
          onClick={() => chartRef.current?.timeScale().scrollToRealTime()}
          className="absolute bottom-3 right-3 z-10 flex items-center gap-1.5 rounded-md border border-info/40 bg-card/90 px-2.5 py-1.5 text-xs font-medium text-info hover:bg-info/10 transition-colors"
        >
          <RadioTower className="size-3" /> Go to Live
        </button>
      )}

      {loading && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground bg-card/60">
          Loading chart…
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-bearish bg-card/80">
          Chart data unavailable: {error}
        </div>
      )}
    </div>
  );
});
