import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryPanel } from "./memory-panel";
import type { MemoryRecord } from "@/lib/types";

const { memoryList, memoryCreate, memoryArchive } = vi.hoisted(() => ({
  memoryList: vi.fn(), memoryCreate: vi.fn(), memoryArchive: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  api: { memoryList, memoryCreate, memoryArchive },
  ApiError: class ApiError extends Error {},
}));

const sample: MemoryRecord = {
  id: 1, category: "TRADE_LESSON", content: "Enters too early before the retracement.",
  source: "user_confirmed", status: "ACTIVE",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", strategy_version: null,
};

describe("MemoryPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts collapsed and does not fetch memories until expanded", () => {
    render(<MemoryPanel />);
    expect(screen.getByText("Trading memory")).toBeInTheDocument();
    expect(memoryList).not.toHaveBeenCalled();
  });

  it("lists active memories once expanded", async () => {
    memoryList.mockResolvedValue([sample]);
    render(<MemoryPanel />);
    fireEvent.click(screen.getByText("Trading memory"));
    await waitFor(() => expect(screen.getByText(sample.content)).toBeInTheDocument());
  });

  it("expands and prefills the content field when a prefill prop is given", () => {
    memoryList.mockResolvedValue([]);
    render(<MemoryPanel prefill="Draft lesson text" onPrefillConsumed={() => {}} />);
    expect(screen.getByDisplayValue("Draft lesson text")).toBeInTheDocument();
  });

  it("calls memoryCreate with the entered content and category, then refreshes", async () => {
    memoryList.mockResolvedValue([]);
    memoryCreate.mockResolvedValue(sample);
    render(<MemoryPanel />);
    fireEvent.click(screen.getByText("Trading memory"));
    await waitFor(() => expect(memoryList).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByPlaceholderText(/Describe the preference/), {
      target: { value: "A new lesson" },
    });
    fireEvent.click(screen.getByText("Save to memory"));

    await waitFor(() => expect(memoryCreate).toHaveBeenCalledWith(
      expect.objectContaining({ content: "A new lesson", category: "TRADE_LESSON" })
    ));
    await waitFor(() => expect(memoryList).toHaveBeenCalledTimes(2));
  });

  it("does not call memoryCreate when content is empty", () => {
    memoryList.mockResolvedValue([]);
    render(<MemoryPanel />);
    fireEvent.click(screen.getByText("Trading memory"));
    const saveButton = screen.getByText("Save to memory") as HTMLButtonElement;
    expect(saveButton.disabled).toBe(true);
  });

  it("archives a memory and removes it from the visible list", async () => {
    memoryList.mockResolvedValue([sample]);
    memoryArchive.mockResolvedValue({ ...sample, status: "ARCHIVED" });
    render(<MemoryPanel />);
    fireEvent.click(screen.getByText("Trading memory"));
    await waitFor(() => expect(screen.getByText(sample.content)).toBeInTheDocument());

    fireEvent.click(screen.getByTitle("Archive this memory"));

    await waitFor(() => expect(memoryArchive).toHaveBeenCalledWith(sample.id));
    await waitFor(() => expect(screen.queryByText(sample.content)).not.toBeInTheDocument());
  });
});
