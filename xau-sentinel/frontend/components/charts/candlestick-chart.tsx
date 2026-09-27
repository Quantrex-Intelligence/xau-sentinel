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
import type { Candle, Liquidity, Setup, Timeframe } from "@/lib/types";

const ZONE_COLORS: Record<string, string> = {
  "Previous Day High": "#e06c75", "Previous Day Low": "#e06c75",
  "Current Day High": "#c678dd", "Current Day Low": "#c678dd",
  "Asian High": "#d19a66", "Asian Low": "#d19a66",
  "London High": "#56b6c2", "London Low": "#56b6c2",
  "H1 Swing High": "#98c379", "H1 Swing Low": "#98c379",
  "H4 Swing High": "#e5c07b", "H4 Swing Low": "#e5c07b",
  "VWAP": "#abb2bf",
};

const DEFAULT_CHART_ZONES = ["Previous Day High", "Previous Day Low", "Current Day High", "Current Day Low", "VWAP"];

export interface ChartOverlayToggles {
  zones: boolean;
  liquidity: boolean;
  setup: boolean;
}

export function CandlestickChart({
  timeframe,
  zones,
  liquidity,
  setup,
  latestCandle,
  overlays,
}: {
  timeframe: Timeframe;
  zones: Record<string, number>;
  liquidity: Liquidity;
  setup: Setup | null;
  latestCandle: Candle | null;
  overlays: ChartOverlayToggles;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  // Tracks which timeframe the last fetch outcome belongs to, so "loading"
  // is derived (true whenever the current `timeframe` hasn't resolved yet)
  // instead of set synchronously at the top of the fetch effect.
  const [fetchResult, setFetchResult] = useState<{ timeframe: Timeframe; error: string | null } | null>(null);
  const loading = fetchResult?.timeframe !== timeframe;
  const error = fetchResult?.timeframe === timeframe ? fetchResult.error : null;

  // Chart lifecycle: created once, disposed on unmount.
  useEffect(() => {
    if (!containerRef.current) return;
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
    return () => {
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
        if (cancelled || !seriesRef.current) return;
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
    if (timeframe !== "M5" || !latestCandle || !seriesRef.current) return;
    seriesRef.current.update({
      time: latestCandle.time as UTCTimestamp,
      open: latestCandle.open, high: latestCandle.high,
      low: latestCandle.low, close: latestCandle.close,
    });
  }, [latestCandle, timeframe]);

  // Zone price lines.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const lines = (overlays.zones ? Object.keys(zones) : []).filter((name) =>
      DEFAULT_CHART_ZONES.includes(name)
    );
    const created = lines.map((name) =>
      series.createPriceLine({
        price: zones[name],
        color: ZONE_COLORS[name] ?? "#abb2bf",
        lineWidth: 1,
        lineStyle: 2,
        title: name,
      })
    );
    return () => created.forEach((l) => series.removePriceLine(l));
  }, [zones, overlays.zones]);

  // Setup entry/SL/TP price lines.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !overlays.setup || setup?.state !== "VALID") return;
    const created: IPriceLine[] = [];
    if (setup.stop_loss !== null)
      created.push(series.createPriceLine({ price: setup.stop_loss, color: "#ef5350", lineWidth: 2, lineStyle: 0, title: "SL" }));
    if (setup.take_profit !== null)
      created.push(series.createPriceLine({ price: setup.take_profit, color: "#26a69a", lineWidth: 2, lineStyle: 0, title: "TP" }));
    if (setup.entry_zone)
      created.push(series.createPriceLine({ price: setup.entry_zone[0], color: "#61afef", lineWidth: 1, lineStyle: 3, title: "Entry" }));
    return () => created.forEach((l) => series.removePriceLine(l));
  }, [setup, overlays.setup]);

  // Liquidity sweep / equal-level markers.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    if (!overlays.liquidity) {
      const plugin = createSeriesMarkers(series, []);
      return () => plugin.detach();
    }
    // No text labels — with several events clustered close together on M5
    // the labels overlapped into an unreadable pile; shape + color + the
    // hoverable tooltip-free legend (sweeps arrows, equal-levels dots) is
    // enough to read at a glance, matching "do not overcrowd the chart."
    const markers: SeriesMarker<Time>[] = [
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
    ];
    const plugin = createSeriesMarkers(series, markers);
    return () => plugin.detach();
  }, [liquidity, overlays.liquidity]);

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
