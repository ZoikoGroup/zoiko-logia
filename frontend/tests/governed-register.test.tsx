import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GovernedRegister, type RegisterRecord } from "@/components/governance/GovernedRegister";
const records: RegisterRecord[] = Array.from({ length: 12 }, (_, i) => ({ id: `record-${i}`, title: `Source ${String(i).padStart(2, "0")}`, category: i % 2 ? "Tax" : "Accounting", scope: i % 2 ? "UK" : "US", state: i % 2 ? "Pending" : "Approved", owner: `Owner ${i}`, facts: { "Authority": `Issuer ${i}` }, evidence: [`Evidence for record ${i}`], history: [`Revision ${i}`] }));
function setup(items = records) { render(<GovernedRegister title="Source register" inspector="Source inspector" records={items} metrics={[]} doctrine="Check source rights." />); }
describe("Governed register interactions", () => {
  it("selects actual record evidence and inspector history", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Source 03" }));
    const inspector = within(screen.getByRole("complementary", { name: "Source inspector" }));
    expect(inspector.getByText("Issuer 3")).toBeInTheDocument();
    expect(inspector.getByText("Evidence for record 3")).toBeInTheDocument();
    fireEvent.click(inspector.getByRole("button", { name: "History" }));
    expect(inspector.getByText("Revision 3")).toBeInTheDocument();
    expect(inspector.queryByText("Issuer 3")).not.toBeInTheDocument();
  });
  it("combines search and state/scope filters and resets them", () => {
    setup();
    fireEvent.change(screen.getByRole("textbox", { name: "Search Source register" }), { target: { value: "Owner 3" } });
    expect(screen.getByText("1 matching records · 12 loaded")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Filter by state" }), { target: { value: "Approved" } });
    expect(screen.getByText("No records match these filters.")).toBeInTheDocument();
    expect(screen.queryByRole("complementary")?.textContent).not.toContain("Issuer 3");
    fireEvent.click(screen.getByRole("button", { name: "Reset register filters" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Filter by scope" }), { target: { value: "UK" } });
    expect(screen.getByText("6 matching records · 12 loaded")).toBeInTheDocument();
  });
  it("paginates and applies categories to the full loaded catalog", () => {
    setup();
    expect(screen.queryByRole("button", { name: "Source 11" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("button", { name: "Source 11" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tax" }));
    expect(screen.getByText("1 / 1")).toBeInTheDocument();
    expect(screen.getByText("6 matching records · 12 loaded")).toBeInTheDocument();
  });
  it("clears stale inspector content when the available records change", () => {
    const { rerender } = render(<GovernedRegister title="Source register" inspector="Source inspector" records={records} metrics={[]} doctrine="Check rights" />);
    rerender(<GovernedRegister title="Source register" inspector="Source inspector" records={[]} metrics={[]} doctrine="Check rights" />);
    expect(screen.getByText("Select an available record to inspect it.")).toBeInTheDocument();
    expect(screen.queryByText("Issuer 0")).not.toBeInTheDocument();
  });
  it("keeps the inspector on the visible page after selecting and paginating", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Source 03" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    const inspector = within(screen.getByRole("complementary", { name: "Source inspector" }));
    expect(inspector.getByText("Issuer 10")).toBeInTheDocument();
    expect(inspector.queryByText("Issuer 3")).not.toBeInTheDocument();
  });
});
