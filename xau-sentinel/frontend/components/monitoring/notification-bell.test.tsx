import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NotificationBell } from "./notification-bell";
import type { AlertExplanation, MonitoringAlert } from "@/lib/types";

const { unreadAlerts, monitoringAlerts, acknowledgeAlert, acknowledgeAllAlerts, explainAlert } = vi.hoisted(() => ({
  unreadAlerts: vi.fn(),
  monitoringAlerts: vi.fn(),
  acknowledgeAlert: vi.fn(),
  acknowledgeAllAlerts: vi.fn(),
  explainAlert: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  api: { unreadAlerts, monitoringAlerts, acknowledgeAlert, acknowledgeAllAlerts, explainAlert },
}));

function alert(overrides: Partial<MonitoringAlert> = {}): MonitoringAlert {
  return {
    id: 1, type: "SETUP_STATE_CHANGED", severity: "INFO", title: "Setup changed",
    message: "XAUUSD setup moved from NO SETUP to DEVELOPING.", symbol: "XAUUSD",
    payload: {}, dedup_key: "k1", acknowledged: false, timestamp: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function explanation(overrides: Partial<AlertExplanation> = {}): AlertExplanation {
  return {
    subject_type: "alert", subject_id: 1, explanation_type: "SETUP_STATE_CHANGED",
    summary: "XAUUSD setup moved from NO SETUP to DEVELOPING.",
    deterministic_facts: ["Previous state: NO SETUP", "Current state: DEVELOPING"],
    supporting_context: [], risk_context: [], historical_context: "", knowledge_context: [],
    memory_context: [], uncertainties: ["No sufficiently similar historical setups were found."],
    interpretation: "The setup moved forward after a liquidity sweep and MSS confirmation.",
    sources: [], generated_at: "2026-01-01T00:00:00Z",
    llm_provider: "mock", llm_model: "mock-model", llm_error: null,
    ...overrides,
  };
}

describe("NotificationBell", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows no unread badge when there are no alerts", async () => {
    unreadAlerts.mockResolvedValue([]);
    render(<NotificationBell />);
    await waitFor(() => expect(unreadAlerts).toHaveBeenCalled());
    expect(screen.queryByText(/^\d+$/)).not.toBeInTheDocument();
  });

  it("shows an unread count badge matching the number of alerts", async () => {
    unreadAlerts.mockResolvedValue([alert({ id: 1 }), alert({ id: 2, dedup_key: "k2" })]);
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("2")).toBeInTheDocument());
  });

  it("opens a dropdown showing alert messages when the bell is clicked", async () => {
    unreadAlerts.mockResolvedValue([alert({ message: "A+ setup detected — BUY" })]);
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText("Notifications"));
    expect(await screen.findByText("A+ setup detected — BUY")).toBeInTheDocument();
  });

  it("distinguishes an APLUS_SETUP_DETECTED alert with an A+ badge", async () => {
    unreadAlerts.mockResolvedValue([alert({ type: "APLUS_SETUP_DETECTED", message: "A+ setup confirmed" })]);
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Notifications"));

    await screen.findByText("A+ setup confirmed");
    expect(screen.getByText("A+")).toBeInTheDocument();
  });

  it("shows the correct severity badge for a CRITICAL alert", async () => {
    unreadAlerts.mockResolvedValue([alert({ severity: "CRITICAL", message: "FundedNext risk breached" })]);
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Notifications"));

    await screen.findByText("FundedNext risk breached");
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
  });

  it("acknowledging an alert calls the API and removes it from the unread list", async () => {
    unreadAlerts.mockResolvedValue([alert({ id: 5, message: "Setup changed" })]);
    acknowledgeAlert.mockResolvedValue({ acknowledged: true });
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Notifications"));

    await screen.findByText("Setup changed");
    fireEvent.click(screen.getByText("Acknowledge"));

    await waitFor(() => expect(acknowledgeAlert).toHaveBeenCalledWith(5));
    await waitFor(() => expect(screen.queryByText("Setup changed")).not.toBeInTheDocument());
  });

  it("mark all as read calls acknowledgeAllAlerts and clears the unread list", async () => {
    unreadAlerts.mockResolvedValue([alert({ id: 1 }), alert({ id: 2, dedup_key: "k2" })]);
    acknowledgeAllAlerts.mockResolvedValue({ acknowledged: true, count: 2 });
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("2")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Notifications"));

    await screen.findByText("Mark all as read");
    fireEvent.click(screen.getByText("Mark all as read"));

    await waitFor(() => expect(acknowledgeAllAlerts).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("No unread alerts.")).toBeInTheDocument());
  });

  it('"Show all" fetches and renders the fuller alert history', async () => {
    unreadAlerts.mockResolvedValue([]);
    monitoringAlerts.mockResolvedValue([alert({ id: 9, message: "Historical alert", acknowledged: true })]);
    render(<NotificationBell />);
    await waitFor(() => expect(unreadAlerts).toHaveBeenCalled());
    fireEvent.click(screen.getByLabelText("Notifications"));

    fireEvent.click(await screen.findByText("Show all"));

    await waitFor(() => expect(monitoringAlerts).toHaveBeenCalledWith({ limit: "50" }));
    expect(await screen.findByText("Historical alert")).toBeInTheDocument();
  });

  it("never renders probability or win-forecast language", async () => {
    unreadAlerts.mockResolvedValue([alert({ message: "This CPI print means gold will rise." })]);
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Notifications"));
    await screen.findByText(/This CPI print/);
    const bodyText = document.body.textContent ?? "";
    expect(bodyText.toLowerCase()).not.toContain("probability");
    expect(bodyText.toLowerCase()).not.toContain("chance of");
  });

  it("clicking Explain fetches and renders the structured explanation", async () => {
    unreadAlerts.mockResolvedValue([alert({ id: 7, message: "Setup changed" })]);
    explainAlert.mockResolvedValue(explanation({
      subject_id: 7,
      interpretation: "The setup moved forward after a liquidity sweep and MSS confirmation.",
    }));
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Notifications"));
    await screen.findByText("Setup changed");

    fireEvent.click(screen.getByText("Explain"));

    await waitFor(() => expect(explainAlert).toHaveBeenCalledWith(7));
    expect(await screen.findByText("Previous state: NO SETUP")).toBeInTheDocument();
    expect(screen.getByText("Current state: DEVELOPING")).toBeInTheDocument();
    expect(screen.getByText("The setup moved forward after a liquidity sweep and MSS confirmation.")).toBeInTheDocument();
  });

  it("omits empty explanation sections rather than padding them", async () => {
    unreadAlerts.mockResolvedValue([alert({ id: 7 })]);
    explainAlert.mockResolvedValue(explanation({ subject_id: 7, supporting_context: [], risk_context: [] }));
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Notifications"));
    fireEvent.click(await screen.findByText("Explain"));

    await screen.findByText(/liquidity sweep and MSS confirmation/);
    expect(screen.queryByText("Context")).not.toBeInTheDocument();
    expect(screen.queryByText("Risk")).not.toBeInTheDocument();
  });

  it("shows a safe fallback when the explanation fetch fails, never a crash", async () => {
    unreadAlerts.mockResolvedValue([alert({ id: 7 })]);
    explainAlert.mockRejectedValue(new Error("network error"));
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Notifications"));
    fireEvent.click(await screen.findByText("Explain"));

    expect(await screen.findByText("Explanation unavailable.")).toBeInTheDocument();
  });

  it("toggling Explain twice hides the explanation without refetching", async () => {
    unreadAlerts.mockResolvedValue([alert({ id: 7 })]);
    explainAlert.mockResolvedValue(explanation({ subject_id: 7 }));
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Notifications"));
    fireEvent.click(await screen.findByText("Explain"));
    await screen.findByText(/liquidity sweep and MSS confirmation/);

    fireEvent.click(screen.getByText("Hide explanation"));
    expect(screen.queryByText(/liquidity sweep and MSS confirmation/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Explain"));
    await screen.findByText(/liquidity sweep and MSS confirmation/);
    expect(explainAlert).toHaveBeenCalledTimes(1);
  });
});
