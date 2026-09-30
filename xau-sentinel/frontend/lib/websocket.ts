"use client";

import { useEffect, useRef, useState } from "react";
import type { MarketSnapshot } from "./types";

const RECONNECT_DELAY_MS = 3000;

// DEP-001: same shared-secret token as lib/api.ts. A browser WebSocket
// constructor can't set a custom header, so the token travels as a query
// param instead — checked by api/main.py's AuthMiddleware before accept().
const AUTH_TOKEN = process.env.NEXT_PUBLIC_API_AUTH_TOKEN ?? "";

// Same-origin by default (proxied to the API by next.config.ts's /ws rewrite);
// NEXT_PUBLIC_WS_URL overrides it for a directly reachable API.
function resolveWsUrl(): string {
  const base = process.env.NEXT_PUBLIC_WS_URL
    ? process.env.NEXT_PUBLIC_WS_URL
    : (() => {
        const { protocol, host } = window.location;
        return `${protocol === "https:" ? "wss" : "ws"}://${host}/ws/market`;
      })();
  if (!AUTH_TOKEN) return base;
  const url = new URL(base);
  url.searchParams.set("token", AUTH_TOKEN);
  return url.toString();
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
