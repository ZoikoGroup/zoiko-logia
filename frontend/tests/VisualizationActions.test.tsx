import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { VisualizationActions } from "@/components/VisualizationActions";

describe("VisualizationActions", () => {
  it("only renders the actions the caller actually supplies", () => {
    render(<VisualizationActions onExportCsv={() => {}} />);
    expect(screen.getByRole("button", { name: /export csv/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /download png/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^save$/i })).toBeNull();
  });

  it("renders nothing when no action is supported", () => {
    const { container } = render(<VisualizationActions />);
    expect(container.firstChild).toBeNull();
  });

  it("is operable entirely from the keyboard", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(true);
    render(<VisualizationActions onSave={onSave} />);

    await user.tab(); // focus moves to the native <button>
    const button = screen.getByRole("button", { name: /^save$/i });
    expect(button).toHaveFocus();

    await user.keyboard("{Enter}");
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  });

  it("does not fire a duplicate save when the button is clicked repeatedly before the first save resolves", async () => {
    const user = userEvent.setup();
    let resolveSave: (value: boolean) => void = () => {};
    const onSave = vi.fn(() => new Promise<boolean>((resolve) => { resolveSave = resolve; }));
    render(<VisualizationActions onSave={onSave} />);

    const button = screen.getByRole("button", { name: /^save$/i });
    await user.click(button);
    await user.click(button); // fired again before the first attempt resolved
    await user.click(button);

    expect(onSave).toHaveBeenCalledTimes(1);
    resolveSave(true);
    await waitFor(() => expect(screen.getByText("Done")).toBeTruthy());
  });

  it("shows a failure state without crashing when an action rejects", async () => {
    const user = userEvent.setup();
    const onDownloadPng = vi.fn().mockRejectedValue(new Error("boom"));
    render(<VisualizationActions onDownloadPng={onDownloadPng} />);
    await user.click(screen.getByRole("button", { name: /download png/i }));
    await waitFor(() => expect(screen.getByText(/failed/i)).toBeTruthy());
  });
});
