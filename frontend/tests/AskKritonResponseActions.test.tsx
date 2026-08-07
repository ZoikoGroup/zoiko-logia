import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AskKritonResponse, SavedAnswerCreateRequest } from "@/lib/api";

const answered: AskKritonResponse = {
  query_id: "q-1",
  correlation_id: "corr-1",
  outcome: "answered",
  route: "LLM",
  safety: { risk_level: "LOW", policy_state: "allowed", disclaimer_required: false },
  confidence_state: "sufficient",
  source_bundle: null,
  answer: {
    text: "Standard deduction for 2026 is $32,200 [REF-1] for married filing jointly.",
    citations: [
      { ref_id: "REF-1", source_id: "src-irs", title: "IRS Rev. Proc. 2025-32", url: "https://irs.gov/pub/rp-25-32" },
      { ref_id: "REF-2", source_id: "src-notice", title: "IRS Notice 2026-1", url: null },
    ],
    limitations: ["Figures apply to the 2026 tax year only."],
  },
  next_action: null,
  audit_reference: { audit_chain_id: "audit-1" },
};

let authToken: string | null = "test-token";
let askImpl: () => Promise<AskKritonResponse> = async () => answered;
const askCalls: { query: string }[] = [];
const saveCalls: SavedAnswerCreateRequest[] = [];
let saveShouldFail = false;

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getAuthToken: () => authToken,
    askKriton: vi.fn(async (_token: string, payload: { query: string }) => {
      askCalls.push({ query: payload.query });
      return askImpl();
    }),
    createSavedAnswer: vi.fn(async (_token: string, payload: SavedAnswerCreateRequest) => {
      if (saveShouldFail) throw new actual.ApiError(500, "Saved answer store unavailable");
      saveCalls.push(payload);
      return { id: "saved-1", ...payload, tags: [], created_at: "2026-01-01T00:00:00Z" };
    }),
  };
});

// The answer body's rich renderers are exercised by their own suites; stubbing
// them here keeps this test about the response actions rather than about
// chart runtimes that do not lay out under jsdom.
vi.mock("@/components/AnswerVisualizations", () => ({ AnswerVisualizations: () => null }));
vi.mock("@/components/CalculationWidget", () => ({ CalculationWidget: () => null }));
// Mirrors the real component's no-blocks branch, which renders the answer
// prose through the page's own markdown renderer — the path that produces the
// narrative tables asserted on below. Stubbing it to null would have hidden
// them entirely.
vi.mock("@/components/DynamicAnswerBlocks", () => ({
  DynamicAnswerBlocks: ({ answer, renderMarkdown }: {
    answer: { text: string; blocks?: unknown[] };
    renderMarkdown: (text: string) => React.ReactNode;
  }) => <>{renderMarkdown(answer.text)}</>,
}));

const { default: AskKritonPage } = await import("@/app/ask-kriton/page");

/** Captured object-URL downloads, so a click can be asserted on without a
 * real filesystem. jsdom implements neither createObjectURL nor navigation. */
const downloads: { filename: string; body: string }[] = [];

function stubDownloadPipeline() {
  const blobs = new Map<string, Blob>();
  let counter = 0;
  URL.createObjectURL = vi.fn((blob: Blob) => {
    const url = `blob:mock/${(counter += 1)}`;
    blobs.set(url, blob);
    return url;
  });
  URL.revokeObjectURL = vi.fn();
  // The component drives the download by clicking a detached <a download>.
  HTMLAnchorElement.prototype.click = function click(this: HTMLAnchorElement) {
    const blob = blobs.get(this.href);
    if (!blob) return;
    // Blob.text() is async; the anchor is revoked synchronously right after
    // click, so read the recorded blob rather than the live URL.
    void blob.text().then((body) => downloads.push({ filename: this.download, body }));
  };
}

async function askAQuestion(user: ReturnType<typeof userEvent.setup>, text: string) {
  const composer = screen.getByPlaceholderText("Ask Kriton...");
  await user.click(composer);
  await user.paste(text);
  await user.keyboard("{Enter}");
}

beforeEach(() => {
  authToken = "test-token";
  askImpl = async () => answered;
  saveShouldFail = false;
  askCalls.length = 0;
  saveCalls.length = 0;
  downloads.length = 0;
  window.localStorage.clear();
  // jsdom implements no layout, so the page's scroll-to-latest-turn effect
  // has nothing to call.
  Element.prototype.scrollIntoView = vi.fn();
  stubDownloadPipeline();
  // Reads go through userEvent.setup()'s own clipboard stub, which it
  // installs over navigator.clipboard for the duration of each test.
});

describe("composer keyboard submission", () => {
  it("sends the query on Enter", async () => {
    const user = userEvent.setup();
    render(<AskKritonPage />);
    await askAQuestion(user, "What is the 2026 standard deduction?");
    await waitFor(() => expect(askCalls).toHaveLength(1));
    expect(askCalls[0].query).toBe("What is the 2026 standard deduction?");
  });

  it("inserts a newline instead of sending on Shift+Enter", async () => {
    const user = userEvent.setup();
    render(<AskKritonPage />);
    const composer = screen.getByPlaceholderText("Ask Kriton...") as HTMLTextAreaElement;
    await user.click(composer);
    await user.paste("first line");
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    await user.paste("second line");

    expect(askCalls).toHaveLength(0);
    expect(composer.value).toBe("first line\nsecond line");
  });

  it("does not send while an IME composition is active", async () => {
    render(<AskKritonPage />);
    const composer = screen.getByPlaceholderText("Ask Kriton...") as HTMLTextAreaElement;
    // Enter commits the candidate word for Japanese/Chinese/Korean input; it
    // must never be read as "send" or the query fires mid-word.
    composer.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", isComposing: true, bubbles: true, cancelable: true }),
    );
    expect(askCalls).toHaveLength(0);
  });

  it("ignores Enter on an empty composer", async () => {
    const user = userEvent.setup();
    render(<AskKritonPage />);
    await user.click(screen.getByPlaceholderText("Ask Kriton..."));
    await user.keyboard("{Enter}");
    expect(askCalls).toHaveLength(0);
  });
});

describe("per-answer response actions", () => {
  async function renderAnsweredTurn() {
    const user = userEvent.setup();
    render(<AskKritonPage />);
    await askAQuestion(user, "What is the 2026 standard deduction?");
    await waitFor(() => expect(screen.getByRole("button", { name: /^copy$/i })).toBeTruthy());
    return user;
  }

  it("copies the answer as markdown with sources and without internal ref markers", async () => {
    const user = await renderAnsweredTurn();
    await user.click(screen.getByRole("button", { name: /^copy$/i }));

    await waitFor(() => expect(screen.getByText("Copied")).toBeTruthy());
    const copied = await navigator.clipboard.readText();
    expect(copied).toContain("# What is the 2026 standard deduction?");
    expect(copied).toContain("$32,200");
    expect(copied).not.toContain("[REF-1]"); // internal marker, meaningless outside the app
    expect(copied).toContain("## Sources");
    expect(copied).toContain("REF-1: IRS Rev. Proc. 2025-32 — https://irs.gov/pub/rp-25-32");
    expect(copied).toContain("REF-2: IRS Notice 2026-1");
    expect(copied).toContain("## Limitations");
    expect(copied).toContain("Risk: LOW");
  });

  it("downloads the same markdown under a filesystem-safe name", async () => {
    const user = await renderAnsweredTurn();
    await user.click(screen.getByRole("button", { name: /download \.md/i }));

    await waitFor(() => expect(downloads).toHaveLength(1));
    expect(downloads[0].filename).toBe("what-is-the-2026-standard-deduction.md");
    expect(downloads[0].body).toContain("## Sources");
    // Clipboard and file must never disagree — both come from answerAsMarkdown.
    await user.click(screen.getByRole("button", { name: /^copy$/i }));
    await waitFor(() => expect(screen.getByText("Copied")).toBeTruthy());
    expect(downloads[0].body).toBe(await navigator.clipboard.readText());
  });

  it("saves the answer against its query id", async () => {
    const user = await renderAnsweredTurn();
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saveCalls).toHaveLength(1));
    expect(saveCalls[0]).toMatchObject({
      query_id: "q-1",
      query_text: "What is the 2026 standard deduction?",
      risk_level: "LOW",
    });
    expect(saveCalls[0].answer_text).toContain("[REF-1]"); // stored answer keeps its audit markers
    await waitFor(() => expect(screen.getByText("Saved")).toBeTruthy());
  });

  it("surfaces a save failure instead of silently doing nothing", async () => {
    saveShouldFail = true;
    const user = await renderAnsweredTurn();
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(screen.getByText("Saved answer store unavailable")).toBeTruthy());
    expect(saveCalls).toHaveLength(0);
  });

  it("puts the original prompt back in the composer when reused", async () => {
    const user = await renderAnsweredTurn();
    await user.click(screen.getByRole("button", { name: /reuse prompt/i }));
    const composer = screen.getByPlaceholderText("Ask a follow-up...") as HTMLTextAreaElement;
    expect(composer.value).toBe("What is the 2026 standard deduction?");
    expect(askCalls).toHaveLength(1); // reuse stages the prompt, it does not resend
  });

  it("shows the sources disclosure open, with a count", async () => {
    await renderAnsweredTurn();
    // "Sources" also names a sidebar nav link — the disclosure is the <summary>.
    const summary = screen.getAllByText("Sources").find((el) => el.tagName === "SUMMARY");
    expect(summary).toBeTruthy();
    expect(summary?.parentElement).toHaveProperty("open", true);
    expect(summary?.textContent).toContain("2");
  });
});

describe("tables inside the answer prose", () => {
  const withTable: AskKritonResponse = {
    ...answered,
    answer: {
      text: [
        "The 2026 standard deduction amounts are:",
        "",
        "| Filing status | 2025 | 2026 |",
        "| --- | ---: | ---: |",
        "| Married Filing Jointly | $31,500 | $32,200 |",
        "| Single | $15,750 | $16,100 |",
      ].join("\n"),
      citations: [],
      limitations: [],
    },
  };

  it("copies a narrative table as TSV exactly as displayed", async () => {
    askImpl = async () => withTable;
    const user = userEvent.setup();
    render(<AskKritonPage />);
    await askAQuestion(user, "Standard deduction table");

    await user.click(await screen.findByRole("button", { name: /copy table/i }));
    await waitFor(() => expect(screen.getByText("Copied")).toBeTruthy());

    const copied = await navigator.clipboard.readText();
    expect(copied.split("\n")).toEqual([
      "Filing status\t2025\t2026",
      "Married Filing Jointly\t$31,500\t$32,200",
      "Single\t$15,750\t$16,100",
    ]);
  });

  it("renders no copy control for an answer that has no table", async () => {
    const user = userEvent.setup();
    render(<AskKritonPage />);
    await askAQuestion(user, "No table here");
    await waitFor(() => expect(screen.getByRole("button", { name: /^copy$/i })).toBeTruthy());
    expect(screen.queryByRole("button", { name: /copy table/i })).toBeNull();
  });
});

describe("whole-thread download", () => {
  it("exports every turn, including ones that failed", async () => {
    const user = userEvent.setup();
    render(<AskKritonPage />);
    await askAQuestion(user, "First question");
    await waitFor(() => expect(screen.getByRole("button", { name: /^copy$/i })).toBeTruthy());

    askImpl = async () => { throw new Error("network down"); };
    const followUp = screen.getByPlaceholderText("Ask a follow-up...");
    await user.click(followUp);
    await user.paste("Second question");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(askCalls).toHaveLength(2));

    await user.click(screen.getByRole("button", { name: /conversation options|more/i }).closest("button")!);
    await user.click(await screen.findByText("Download"));

    await waitFor(() => expect(downloads).toHaveLength(1));
    const body = downloads[0].body;
    expect(body).toContain("**Turns:** 2");
    expect(body).toContain("First question");
    expect(body).toContain("Second question");
    expect(body).toContain("_[failed]_"); // an errored turn is recorded, not dropped
  });
});
