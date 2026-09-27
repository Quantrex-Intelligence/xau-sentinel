/**
 * Typed fetch wrappers around the FastAPI layer. No trading logic — every
 * function here is a 1:1 call to a route in api/routes/, which is itself a
 * 1:1 call into the Python engine. See lib/types.ts for the response shapes.
 */
import type {
  AiConfig,
  AlertItem,
  Analytics,
  Candle,
  ChatRequest,
  ChatResponse,
  EventItem,
  FundedNextRuleSet,
  FundedNextSettings,
  FundedNextStatus,
  Liquidity,
  MarketSnapshot,
  Regime,
  Risk,
  Settings,
  Setup,
  StrategyEvaluation,
  Structure,
  Timeframe,
  Trade,
  TradeCloseInput,
  TradeCreateInput,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      // no JSON body — fall back to statusText
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),

  ticker: () => request<import("./types").PriceInfo>("/api/market/ticker"),
  candles: (timeframe: Timeframe, count = 300) =>
    request<Candle[]>(`/api/market/candles?timeframe=${timeframe}&count=${count}`),
  structure: () => request<Partial<Record<Timeframe, Structure>>>("/api/market/structure"),
  zones: () => request<Record<string, number>>("/api/market/zones"),
  liquidity: () => request<Liquidity>("/api/market/liquidity"),
  regime: () => request<Regime>("/api/market/regime"),
  analysis: () => request<MarketSnapshot>("/api/market/analysis"),

  currentSetup: () => request<Setup>("/api/setup/current"),

  risk: () => request<Risk>("/api/risk"),
  settings: () => request<Settings>("/api/settings"),

  alerts: (limit = 10) => request<AlertItem[]>(`/api/alerts?limit=${limit}`),
  events: (limit = 10) => request<EventItem[]>(`/api/events?limit=${limit}`),

  trades: (filters?: Record<string, string>) => {
    const qs = filters ? `?${new URLSearchParams(filters).toString()}` : "";
    return request<Trade[]>(`/api/journal/trades${qs}`);
  },
  trade: (id: number) => request<Trade>(`/api/journal/trades/${id}`),
  createTrade: (payload: TradeCreateInput) =>
    request<Trade>("/api/journal/trades", { method: "POST", body: JSON.stringify(payload) }),
  closeTrade: (id: number, payload: TradeCloseInput) =>
    request<Trade>(`/api/journal/trades/${id}/close`, { method: "PATCH", body: JSON.stringify(payload) }),
  analytics: (filters?: Record<string, string>) => {
    const qs = filters ? `?${new URLSearchParams(filters).toString()}` : "";
    return request<Analytics>(`/api/journal/analytics${qs}`);
  },

  fundedNextStatus: () => request<FundedNextStatus>("/api/fundednext/status"),
  fundedNextRules: () => request<FundedNextRuleSet[]>("/api/fundednext/rules"),
  fundedNextSettings: () => request<FundedNextSettings>("/api/fundednext/settings"),
  updateFundedNextSettings: (payload: Partial<FundedNextSettings>) =>
    request<FundedNextSettings>("/api/fundednext/settings", { method: "PUT", body: JSON.stringify(payload) }),

  aiConfig: () => request<AiConfig>("/api/ai/config"),
  aiChat: (payload: ChatRequest) =>
    request<ChatResponse>("/api/ai/chat", { method: "POST", body: JSON.stringify(payload) }),

  strategyAPlus: () => request<StrategyEvaluation>("/api/strategy/aplus"),
};
