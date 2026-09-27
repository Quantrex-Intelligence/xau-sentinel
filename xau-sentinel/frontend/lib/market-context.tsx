"use client";

import { createContext, useContext } from "react";
import { useMarketSocket, type SocketStatus } from "./websocket";
import type { MarketSnapshot } from "./types";

interface MarketContextValue {
  snapshot: MarketSnapshot | null;
  status: SocketStatus;
}

export const MarketContext = createContext<MarketContextValue>({ snapshot: null, status: "connecting" });

/** Owns the ONE /ws/market connection for the whole app — mounted once in
 * the root layout so switching pages never opens a second socket. */
export function MarketProvider({ children }: { children: React.ReactNode }) {
  const { snapshot, status } = useMarketSocket();
  return <MarketContext.Provider value={{ snapshot, status }}>{children}</MarketContext.Provider>;
}

export function useMarket() {
  return useContext(MarketContext);
}
