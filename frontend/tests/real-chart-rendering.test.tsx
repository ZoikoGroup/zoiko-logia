import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import * as Adapter from "@/components/visualization/charts/RechartsAdapter";
import { ChartRenderer } from "@/components/visualization/charts/ChartRenderer";
import type { VisualizationSpec } from "@/lib/api";
vi.mock("@/lib/telemetry", () => ({ trackVisualizationInteraction: vi.fn() }));

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function(this: HTMLElement) {
    const height = this.classList.contains("recharts-legend-wrapper") ? 24 : 300;
    return { width:800, height, top:0, left:0, right:800, bottom:height, x:0, y:0, toJSON(){} };
  });
  vi.stubGlobal("ResizeObserver", class { callback: ResizeObserverCallback; constructor(cb:ResizeObserverCallback){this.callback=cb;} observe(target: Element){ this.callback([{ target, contentRect:{ width:800,height:300 } } as ResizeObserverEntry], this as unknown as ResizeObserver); } unobserve(){} disconnect(){} });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("renders real SVG and switches the same validated series from line to bars", async () => {
  vi.stubGlobal("localStorage", { getItem:(key:string) => key.includes("default-view") ? "BAR" : "1", setItem:vi.fn() });
  const viz = { user_requested_type:"line", id:"render-real", type:"LINE", family:"STATISTICAL", renderer:"RECHARTS", title:"Monthly revenue", unit:"GBP",
    encoding:{ x:{field:"period",type:"temporal"}, y:{field:"revenue",type:"quantitative",unit:"GBP"} },
    data:[{x:"2025-01",y:100},{x:"2025-02",y:120},{x:"2025-03",y:90}], series:[], sources:[] } as unknown as VisualizationSpec;
  const before = JSON.stringify(viz);
  const { container } = render(<ChartRenderer viz={viz}/>);
  await waitFor(() => expect(container.querySelector("svg.recharts-surface")).toBeTruthy());
  expect(container.querySelector(".recharts-line-curve")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name:"View" }));
  fireEvent.click(screen.getByRole("menuitemradio", {name:"Bar"}));
  await waitFor(() => expect(container.querySelectorAll(".recharts-bar-rectangle").length).toBe(3));
  fireEvent.click(screen.getByRole("button", {name:/View as table/}));
  expect(screen.getByRole("cell", { name:"2025-01" })).toBeInTheDocument();
  for (const amount of ["100", "120", "90"]) expect(screen.getByRole("cell", {name:amount})).toBeInTheDocument();
  expect(screen.getByText("Units: GBP")).toBeInTheDocument();
  expect(JSON.stringify(viz)).toBe(before);
});

it("puts the unit on the value axis and each bar's value on the bar (QA D01)", async () => {
  vi.stubGlobal("localStorage", { getItem:() => null, setItem:vi.fn() });
  const viz = { id:"d01", type:"BAR", family:"STATISTICAL", renderer:"RECHARTS", title:"F0 2025 quarterly revenue", unit:"USD thousands",
    encoding:{ x:{field:"period",type:"nominal"}, y:{field:"value",type:"quantitative",unit:"USD thousands"} },
    data:[{x:"Q1",y:2100},{x:"Q2",y:2300},{x:"Q3",y:2500},{x:"Q4",y:3100}], series:[], sources:[] } as unknown as VisualizationSpec;
  const { container } = render(<ChartRenderer viz={viz}/>);
  await waitFor(() => expect(container.querySelectorAll(".recharts-bar-rectangle").length).toBe(4));
  const svgText = () => container.querySelector("svg.recharts-surface")?.textContent ?? "";
  expect(svgText()).toContain("USD thousands");
  // Recharts draws the value labels once the bars' entry animation ends.
  await waitFor(() => { for (const value of ["2,100", "2,300", "2,500", "3,100"]) expect(svgText()).toContain(value); },
    { timeout: 4000 });
});

it("reports a renderer exception and keeps the readable dataset", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(Adapter, "RechartsChart").mockImplementation(() => { throw new Error("synthetic render failure"); });
  const viz = { id:"failure", type:"BAR", family:"STATISTICAL", renderer:"RECHARTS", title:"Revenue", data:[{x:"January",y:100},{x:"February",y:120}] } as unknown as VisualizationSpec;
  render(<ChartRenderer viz={viz}/>);
  expect(screen.getByText(/This chart could not be displayed/)).toBeInTheDocument();
  expect(screen.getByRole("cell", {name:"January"})).toBeInTheDocument();
});

it("renders all eight quarterly budget/actual bars and preserves both series in its table", async () => {
  vi.stubGlobal("localStorage", { getItem:() => null, setItem:vi.fn() });
  const budget=[80000,85000,90000,95000], actual=[84000,82000,99000,93000];
  const points=(values:number[]) => values.map((y,i) => ({x:`Q${i+1}`,y}));
  const viz={id:"quarterly-grouped",user_requested_type:"bar",type:"GROUPED_BAR",variant:"GROUPED_BAR_CHART",family:"STATISTICAL",renderer:"RECHARTS",title:"Operating expenses: budget and actual",unit:"GBP",
    encoding:{x:{field:"category",type:"nominal"},y:{field:"value",type:"quantitative",unit:"GBP"}},data:points(budget),
    series:[{name:"Budget",data:points(budget)},{name:"Actual",data:points(actual)}],sources:[]} as unknown as VisualizationSpec;
  const before=JSON.stringify(viz);
  const {container}=render(<ChartRenderer viz={viz}/>);
  await waitFor(() => expect(container.querySelectorAll(".recharts-bar-rectangle").length).toBe(8));
  fireEvent.click(screen.getByRole("button",{name:/View as table/}));
  for(const quarter of ["Q1","Q2","Q3","Q4"]) expect(screen.getByRole("cell",{name:quarter})).toBeInTheDocument();
  for(const value of [...budget,...actual]) expect(screen.getByRole("cell",{name:value.toLocaleString("en-US")})).toBeInTheDocument();
  expect(screen.getByText("Units: GBP")).toBeInTheDocument();
  expect(JSON.stringify(viz)).toBe(before);
});
