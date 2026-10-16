import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Composer } from "@/components/ask-kriton/Composer";

function renderComposer(onSubmit = vi.fn()) {
  render(
    <Composer
      variant="sticky"
      query="What is VAT?"
      onQueryChange={vi.fn()}
      onSubmit={onSubmit}
      attachments={[]}
      onAttachmentsChange={vi.fn()}
      documents={[{ id: "d1", filename: "invoice.pdf", status: "READY", chunk_count: 3 } as never]}
      onUploadComplete={vi.fn()}
      jurisdiction=""
      onJurisdictionChange={vi.fn()}
      submitting={false}
      error={null}
    />,
  );
  return onSubmit;
}

describe("Compact composer", () => {
  it("shows one bar with +, voice and send, and opens the + menu", () => {
    renderComposer();
    expect(screen.getByRole("button", { name: "Voice input" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add documents" }));
    expect(screen.getByRole("menuitem", { name: /Upload documents/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /invoice\.pdf/ })).toBeInTheDocument();
  });

  it("sends the question", () => {
    const onSubmit = renderComposer();
    fireEvent.click(screen.getByRole("button", { name: "Ask follow-up" }));
    expect(onSubmit).toHaveBeenCalled();
  });
});
