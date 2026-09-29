import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NotificationBell } from "./notification-bell";
import type { MonitoringAlert } from "@/lib/types";

const { unreadAlerts, monitoringAlerts, acknowledgeAlert, acknowledgeAllAlerts } = vi.hoisted(() => ({
  unreadAlerts: vi.fn(),
  monitoringAlerts: vi.fn(),
  acknowledgeAlert: vi.fn(),
  acknowledgeAllAlerts: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  api: { unreadAlerts, monitoringAlerts, acknowledgeAlert, acknowledgeAllAlerts },
}));

function alert(overrides: Partial<MonitoringAlert> = {}): MonitoringAlert {
  return {
    id: 1, type: "SETUP_STATE_CHANGED", severity: "INFO", title: "Setup changed",
    message: "XAUUSD setup moved from NO SETUP to DEVELOPING.", symbol: "XAUUSD",
    payload: {}, dedup_key: "k1", acknowledged: false, timestamp: "2026-01-01T00:00:00Z",
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
});
