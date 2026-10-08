"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  type IChartApi,
  type ISeriesApi,
  type IPriceLine,
  type UTCTimestamp,
  createSeriesMarkers,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { api } from "@/lib/api";
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

export function CandlestickChart({
  timeframe,
  zones,
  liquidity,
  analysis,
  aplus,
  latestCandle,
  overlays,
}: {
  timeframe: Timeframe;
  zones: Record<string, number>;
  liquidity: Liquidity;
  analysis: AnalysisV2Response | null;
  aplus: StrategyEvaluation | null;
  latestCandle: Candle | null;
  overlays: ChartOverlayToggles;
}) {
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
    if (!containerRef.current) return;
    disposedRef.current = false;
    const chart = createChart(containerRef.current, {
      layout: { background: { color: "#131722" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#242832" }, horzLines: { color: "#242832" } },
      rightPriceScale: { borderColor: "#242832" },
      timeScale: { borderColor: "#242832", timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
      autoSize: true,
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#26a69a", downColor: "#ef5350",
      wickUpColor: "#26a69a", wickDownColor: "#ef5350",
      borderVisible: false,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    const ict = new IctOverlayPrimitive();
    series.attachPrimitive(ict);
    ictRef.current = ict;
    return () => {
      disposedRef.current = true;
      ictRef.current = null;
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Full history reload on timeframe switch.
  useEffect(() => {
    let cancelled = false;
    api
      .candles(timeframe, 300)
      .then((candles) => {
        if (cancelled || disposedRef.current || !seriesRef.current) return;
        seriesRef.current.setData(
          candles.map((c) => ({
            time: c.time as UTCTimestamp,
            open: c.open, high: c.high, low: c.low, close: c.close,
          }))
        );
        chartRef.current?.timeScale().fitContent();
        if (!cancelled) setFetchResult({ timeframe, error: null });
      })
      .catch((err) => !cancelled && setFetchResult({ timeframe, error: err.message }));
    return () => {
      cancelled = true;
    };
  }, [timeframe]);

  // Incremental update from the live WS snapshot's latest M5 candle — no full rebuild.
  useEffect(() => {
    if (timeframe !== "M5" || !latestCandle || disposedRef.current || !seriesRef.current) return;
    seriesRef.current.update({
      time: latestCandle.time as UTCTimestamp,
      open: latestCandle.open, high: latestCandle.high,
      low: latestCandle.low, close: latestCandle.close,
    });
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

  return (
    <div className="relative w-full h-full min-h-[420px]">
      <div ref={containerRef} className="absolute inset-0" />
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
}
