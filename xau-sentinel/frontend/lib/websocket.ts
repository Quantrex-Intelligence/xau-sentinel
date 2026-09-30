"use client";

import { useEffect, useRef, useState } from "react";
import type { MarketSnapshot } from "./types";

const RECONNECT_DELAY_MS = 3000;

// Same-origin by default (proxied to the API by next.config.ts's /ws rewrite);
// NEXT_PUBLIC_WS_URL overrides it for a directly reachable API.
function resolveWsUrl(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  const { protocol, host } = window.location;
  return `${protocol === "https:" ? "wss" : "ws"}://${host}/ws/market`;
}

export type SocketStatus = "connecting" | "open" | "closed";

/**
 * Owns the single WS /ws/market connection. Each message is already the
 * exact same MarketSnapshot shape GET /api/market/analysis returns (see
 * api/snapshot.py) — this hook does no computation, only reconnection and
 * state plumbing.
 */
export function useMarketSocket() {
  const [snapshot, setSnapshot] = useState<MarketSnapshot | null>(null);
  const [status, setStatus] = useState<SocketStatus>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stoppedRef = useRef(false);

  useEffect(() => {
    stoppedRef.current = false;

    function connect() {
      if (stoppedRef.current) return;
      setStatus("connecting");
      const ws = new WebSocket(resolveWsUrl());
      wsRef.current = ws;

      ws.onopen = () => setStatus("open");
      ws.onmessage = (event) => {
        try {
          setSnapshot(JSON.parse(event.data) as MarketSnapshot);
        } catch {
          // ignore malformed frame
        }
      };
      ws.onclose = () => {
        setStatus("closed");
        if (!stoppedRef.current) {
          timerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };
      ws.onerror = () => ws.close();
    }

    connect();
    return () => {
      stoppedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, []);

  return { snapshot, status };
}
