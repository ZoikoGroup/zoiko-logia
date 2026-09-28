"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  BookOpen,
  Bookmark,
  BriefcaseBusiness,
  CheckCircle2,
  ChevronDown,
  Copy,
  Download,
  Loader2,
  ExternalLink,
  FileText,
  FolderKanban,
  History,
  Lightbulb,
  PenLine,
  RotateCcw,
  Share2,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Sparkles,
  X,
} from "lucide-react";
import { AnswerRenderer } from "@/components/AnswerRenderer";
import {
  askKritonStream,
  createSavedAnswer,
  downloadKritonArtifact,
  getAuthToken,
  listKritonAttachments,
  listEngagements,
  ApiError,
  type AskKritonResponse,
  type SourceCitation,
  type TaskType,
  type RiskLevel,
  type WorkspaceDocument,
} from "@/lib/api";
import {
  answerBodyOnly,
  downloadTextFile,
  safeDownloadName,
  writeTextToClipboard,
} from "@/lib/presentation";
import { getFollowUpSuggestions } from "@/lib/follow-up-suggestions";
import { ThinkingIndicator } from "@/components/ask-kriton/ThinkingIndicator";
import { DesktopSidebar, MobileDrawer } from "@/components/ask-kriton/Sidebar";
import { Composer, attachmentFromDocument, type AttachmentState } from "@/components/ask-kriton/Composer";
import { ExploreFurther } from "@/components/ask-kriton/ExploreFurther";
import { useAuth } from "@/hooks/useAuth";
import {
  loadActiveConversationId,
  loadConversations,
  persistActiveConversationId,
  persistConversations,
  sortConversations,
  type Conversation,
  type Turn,
  type TurnAttachment,
} from "@/lib/ask-kriton-storage";

const QUICK_MODES = [
  { label: "Source check", icon: BookOpen, prompt: "Review this question with eligible source grounding: " },
  { label: "Learn", icon: Lightbulb, prompt: "Explain this as a learning note without giving regulated advice: " },
  { label: "Write", icon: PenLine, prompt: "Draft a professional, source-aware explanation for: " },
  { label: "Workflow", icon: BriefcaseBusiness, prompt: "Turn this into a practical accounting workflow: " },
  { label: "Kriton's choice", icon: Sparkles, prompt: "" },
];

const TASK_TYPES: Array<{ value: TaskType; label: string }> = [
  { value: "general_question", label: "General question" },
  { value: "policy_research", label: "Policy research" },
  { value: "document_evidence_extraction", label: "Document extraction" },
  { value: "reconciliation", label: "Reconciliation" },
];

const RISK_STYLES: Record<RiskLevel, { badge: string; icon: typeof ShieldCheck; label: string }> = {
  ZERO: { badge: "border-line bg-soft text-muted", icon: ShieldCheck, label: "Zero risk" },
  LOW: { badge: "border-ok/30 bg-ok/10 text-ok", icon: ShieldCheck, label: "Low risk" },
  MEDIUM: { badge: "border-info/30 bg-info/10 text-info", icon: ShieldCheck, label: "Medium risk" },
  HIGH: { badge: "border-warn/30 bg-warn/10 text-warn", icon: ShieldAlert, label: "High risk" },
  RESTRICTED: { badge: "border-bad/30 bg-bad/10 text-bad", icon: ShieldOff, label: "Restricted — blocked" },
};

const ROUTE_LABELS: Record<string, string> = {
  // LLM is deliberately absent; the per-turn label below uses actual citation
  // and visualization state instead of asserting provenance from route alone.
  REFUSAL: "Refused — policy blocked",
  CLARIFICATION: "Clarification required",
  HUMAN_REVIEW: "Escalated for human review",
  SECURITY_INCIDENT: "Security incident — blocked",
  REJECTED: "Rejected — invalid request",
};

const OUTCOME_STYLES: Record<string, { label: string; dot: string; text: string }> = {
  answered: { label: "Answered", dot: "bg-ok", text: "text-ok" },
  clarification_required: { label: "Clarification needed", dot: "bg-info", text: "text-info" },
  escalated: { label: "Escalated", dot: "bg-warn", text: "text-warn" },
  limited_response: { label: "Limited", dot: "bg-warn", text: "text-warn" },
  refused: { label: "Refused", dot: "bg-bad", text: "text-bad" },
  rejected: { label: "Blocked", dot: "bg-bad", text: "text-bad" },
};

function genId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function timestamp(): number {
  return Date.now();
}

/** Trailing consecutive clarification_required turns — resets to 0 the moment
 * a turn actually gets answered, so the count reflects one live back-and-forth. */
function clarificationCycleFor(conversation: Conversation | null): number {
  if (!conversation) return 0;
  let cycle = 0;
  for (let i = conversation.turns.length - 1; i >= 0; i--) {
    if (conversation.turns[i].result?.outcome === "clarification_required") cycle++;
    else break;
  }
  return cycle;
}

function ZoikoGlyph({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <div className={`${className} relative shrink-0 overflow-hidden rounded-xl bg-[#16799A] shadow-[0_18px_44px_rgba(0,0,0,0.28)]`}>
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_24%_18%,rgba(255,255,255,0.32),transparent_34%)]" />
      <div className="absolute left-[25%] top-[26%] h-[48%] w-[50%] rounded-sm border-[3px] border-white" />
      <div className="absolute bottom-[31%] left-[36%] h-[26%] w-[8%] bg-[#F3C437]" />
      <div className="absolute bottom-[31%] left-[48%] h-[26%] w-[8%] bg-[#F3C437]" />
      <div className="absolute bottom-[31%] left-[60%] h-[26%] w-[8%] bg-[#F3C437]" />
    </div>
  );
}

/**
 * Keep externally linked citations and uploaded-document evidence visible
 * and verifiable in Kriton's source popup.
 */
function KritonPanel({
  title,
  description,
  onClose,
  children,
}: {
  title: string;
  description: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="absolute inset-0 z-30 flex items-start justify-center bg-ink/20 px-4 pt-20 backdrop-blur-sm" onClick={onClose}>
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-2xl rounded-2xl border border-line bg-panel p-5 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-line pb-4">
          <div>
            <h2 className="text-lg font-bold text-ink">{title}</h2>
            <p className="mt-1 text-sm text-muted">{description}</p>
          </div>
          <button type="button" onClick={onClose} aria-label={`Close ${title}`} className="rounded-lg p-2 text-muted hover:bg-soft hover:text-ink">
            <X size={17} />
          </button>
        </div>
        <div className="max-h-[60vh] overflow-y-auto pt-4">{children}</div>
      </section>
    </div>
  );
}

function externalSourceUrl(rawUrl?: string | null): string | null {
  if (!rawUrl) return null;
  try {
    const url = new URL(rawUrl);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function SourceButton({ citation }: { citation: SourceCitation }) {
  const href = externalSourceUrl(citation.url);
  const content = (
    <>
      <BookOpen size={13} className="mt-0.5 shrink-0 text-brand" />
      <span className="min-w-0 flex-1 truncate">{citation.title || "Untitled source"}</span>
      {href && <ExternalLink size={12} className="mt-0.5 shrink-0 opacity-70 group-hover:opacity-100" />}
    </>
  );

  if (!href) {
    return (
      <div
        className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-xs leading-5 text-muted"
        title="No external link is available for this source"
      >
        {content}
      </div>
    );
  }

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-xs leading-5 text-muted hover:bg-soft hover:text-brand"
    >
      {content}
    </a>
  );
}

/** One answer as a self-contained markdown document — the *export*, as opposed
 * to Copy. Where Copy gives the response body alone (what you paste into an
 * email), this restates the references and the governance metadata so an
 * exported answer stays attributable once it leaves the app. */
function answerAsMarkdown(question: string, result: AskKritonResponse) {
  const answer = result.answer;
  if (!answer) return "";
  const parts = [`# ${question.trim()}`, "", answerBodyOnly(answer.text)];

  const visibleLimitations = answer.limitations.filter(
    (l) => l !== "This response is for educational purposes only. Consult a qualified professional.",
  );
  if (visibleLimitations.length) {
    parts.push("", "## Limitations", "", ...visibleLimitations.map((l) => `- ${l}`));
  }
  if (answer.citations.length) {
    parts.push("", "## Sources", "");
    parts.push(
      ...answer.citations.map((c) => `- ${c.ref_id}: ${c.title}${c.url ? ` — ${c.url}` : ""}`),
    );
  }
  parts.push(
    "",
    "---",
    `Risk: ${result.safety.risk_level} Â· Route: ${result.route} Â· ` +
      `Confidence: ${result.confidence_state.replaceAll("_", " ")} Â· ` +
      `Jurisdiction: ${result.source_bundle?.jurisdiction || "Any"}`,
  );
  return parts.join("\n");
}

/** A whole thread as one markdown transcript — every question with its answer,
 * in order. Turns that never produced an answer (refused, escalated, still
 * loading, errored) are kept and labelled rather than dropped: a transcript
 * that silently omits them would misrepresent the conversation. */
function conversationAsMarkdown(conversation: Conversation) {
  const parts = [`# ${conversation.title}`, ""];
  for (const turn of conversation.turns) {
    parts.push(`## ${turn.submittedQuery.trim()}`, "");
    if (turn.result?.answer) {
      parts.push(answerBodyOnly(turn.result.answer.text), "");
      const citations = turn.result.answer.citations;
      if (citations.length) {
        parts.push("**Sources**", "");
        parts.push(...citations.map((c) => `- ${c.ref_id}: ${c.title}${c.url ? ` — ${c.url}` : ""}`), "");
      }
    } else if (turn.error) {
      parts.push(`_No response — ${turn.error}_`, "");
    } else if (turn.loading) {
      parts.push("_Still awaiting a response._", "");
    } else {
      const action = turn.result?.next_action?.message;
      parts.push(`_No answer composed (${turn.result?.outcome ?? "unknown outcome"})._`, "");
      if (action) parts.push(`> ${action}`, "");
    }
  }
  return parts.join("\n");
}

// Familiar assistant-style action row: lightweight controls immediately
// below the response, with one unambiguous copy action.
// Each button owns a
// short-lived status so the result is visible without a toast system: an
// action that silently succeeds reads as an action that did nothing.
function ResponseActions({
  question,
  result,
  onReuse,
}: {
  question: string;
  result: AskKritonResponse;
  onReuse?: () => void;
}) {
  const [status, setStatus] = useState<Record<string, "idle" | "busy" | "done" | "error">>({});
  const [saveError, setSaveError] = useState("");

  function flash(key: string, value: "done" | "error") {
    setStatus((prev) => ({ ...prev, [key]: value }));
    window.setTimeout(() => setStatus((prev) => ({ ...prev, [key]: "idle" })), 1800);
  }

  // Copy gives the response body ALONE — no disclaimer, no sources, no
  // governance footer. It is the "paste this into an email" action, and the
  // boilerplate the app appends is not part of what Kriton said. Download
  // below is the archival counterpart and keeps all of it.
  async function copyAnswer() {
    try {
      await writeTextToClipboard(answerBodyOnly(result.answer?.text ?? ""));
      flash("copy", "done");
    } catch {
      flash("copy", "error");
    }
  }

  function downloadAnswer() {
    try {
      downloadTextFile(answerAsMarkdown(question, result), safeDownloadName(question, "md"));
      flash("download", "done");
    } catch {
      flash("download", "error");
    }
  }

  async function downloadArtifact(artifact: AskKritonResponse["artifacts"][number]) {
    const token = getAuthToken();
    if (!token) {
      setSaveError("Sign in to download generated documents.");
      return;
    }
    const key = `artifact-${artifact.id}`;
    setStatus((prev) => ({ ...prev, [key]: "busy" }));
    try {
      await downloadKritonArtifact(token, artifact);
      flash(key, "done");
    } catch {
      flash(key, "error");
    }
  }

  // Save is the only action that can fail for a reason the user must act on
  // (signed out, server down), so it surfaces its error text rather than just
  // flashing red.
  async function saveAnswer() {
    const token = getAuthToken();
    if (!token) {
      setSaveError("Sign in to save answers.");
      flash("save", "error");
      return;
    }
    setStatus((prev) => ({ ...prev, save: "busy" }));
    setSaveError("");
    try {
      await createSavedAnswer(token, {
        query_id: result.query_id,
        query_text: question,
        answer_text: result.answer?.text ?? "",
        risk_level: result.safety.risk_level,
      });
      flash("save", "done");
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Could not save this answer.");
      flash("save", "error");
    }
  }

  const actions = [
    { key: "copy", label: "Copy answer", doneLabel: "Copied", icon: Copy, onClick: copyAnswer, title: "Copy the answer text" },
    { key: "download", label: "Download .md", doneLabel: "Downloaded", icon: Download, onClick: downloadAnswer, title: "Download the complete response as Markdown" },
    { key: "save", label: "Save", doneLabel: "Saved", icon: Bookmark, onClick: saveAnswer, title: "Save this answer in Kriton" },
    ...(onReuse
      ? [{ key: "reuse", label: "Reuse prompt", doneLabel: "Reuse prompt", icon: RotateCcw, onClick: onReuse, title: "Put this prompt back in the composer" }]
      : []),
  ];

  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-center gap-0.5" aria-label="Response actions">
      {actions.map(({ key, label, doneLabel, icon: Icon, onClick, title }) => {
        const state = status[key] ?? "idle";
        return (
          <button
            key={key}
            type="button"
            onClick={onClick}
            title={title}
            aria-label={title}
            disabled={state === "busy"}
            className={`inline-flex h-8 min-w-8 items-center justify-center gap-1.5 rounded-lg px-2 text-[11px] font-semibold transition disabled:opacity-50 ${
              state === "error"
                ? "bg-bad/10 text-bad"
                : state === "done"
                  ? "bg-ok/10 text-ok"
                  : "text-muted hover:bg-soft hover:text-ink"
            }`}
          >
            {state === "busy" ? (
              <Loader2 size={16} className="animate-spin" />
            ) : state === "done" ? (
              <CheckCircle2 size={16} />
            ) : (
              <Icon size={16} />
            )}
            <span>{state === "done" ? doneLabel : label}</span>
          </button>
        );
      })}
      {result.answer && result.answer.citations.length > 0 && (
        <details className="group/sources basis-full sm:basis-auto">
          <summary className="flex h-8 cursor-pointer list-none items-center gap-1.5 rounded-lg px-2 text-xs font-semibold text-muted transition hover:bg-soft hover:text-ink">
            <BookOpen size={15} />
            Sources
            <span className="rounded-full bg-soft px-1.5 py-0.5 text-[10px]">{result.answer.citations.length}</span>
            <ChevronDown size={13} className="transition-transform group-open/sources:rotate-180" />
          </summary>
          <div className="mt-1 w-full min-w-0 rounded-xl border border-line bg-panel p-2 shadow-lg sm:w-[420px]">
            <div className="max-h-56 overscroll-contain overflow-y-auto pr-1 [scrollbar-gutter:stable]">
              {result.answer.citations.map((citation) => (
                <SourceButton key={citation.ref_id} citation={citation} />
              ))}
            </div>
          </div>
        </details>
      )}
      </div>
      {(result.artifacts ?? []).length > 0 && (
        <div className="mt-3 space-y-2">
          {result.artifacts.map((artifact) => {
            const key = `artifact-${artifact.id}`;
            const state = status[key] ?? "idle";
            return (
              <button
                key={artifact.id}
                type="button"
                onClick={() => void downloadArtifact(artifact)}
                disabled={state === "busy"}
                className="flex w-full items-center gap-3 rounded-xl border border-brand/30 bg-brand/5 px-3 py-2.5 text-left hover:bg-brand/10 disabled:opacity-60"
              >
                {state === "busy" ? <Loader2 size={17} className="animate-spin text-brand" /> : <FileText size={17} className="text-brand" />}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-semibold text-ink">{artifact.filename}</span>
                  <span className="block text-[11px] text-muted">Generated document Â· Click to download</span>
                </span>
                <Download size={15} className="text-brand" />
              </button>
            );
          })}
        </div>
      )}
      {result.artifact_error && (
        <div className="mt-3 flex items-start gap-2 rounded-xl border border-bad/30 bg-bad/5 px-3 py-2.5 text-xs leading-5 text-bad">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          {result.artifact_error}
        </div>
      )}
      <span className="sr-only" aria-live="polite">
        {Object.entries(status).find(([, state]) => state === "done")?.[0]
          ? "Response action completed"
          : Object.values(status).includes("error") ? "Response action failed" : ""}
      </span>
      {saveError && <p className="mt-1.5 text-[11px] font-medium text-bad">{saveError}</p>}
    </div>
  );
}

/** Hover actions on the user's own question bubble, mirroring the affordances
 * people expect from a chat UI. Kept deliberately separate from
 * ResponseActions: that toolbar acts on Kriton's answer (and can hit the
 * network to save), whereas everything here is local to the question text. */
function QuestionActions({ question, onEdit }: { question: string; onEdit?: () => void }) {
  const [status, setStatus] = useState<Record<string, "idle" | "done" | "error">>({});

  function flash(key: string, value: "done" | "error") {
    setStatus((prev) => ({ ...prev, [key]: value }));
    window.setTimeout(() => setStatus((prev) => ({ ...prev, [key]: "idle" })), 1800);
  }

  async function copyQuestion() {
    try {
      await writeTextToClipboard(question);
      flash("copy", "done");
    } catch {
      flash("copy", "error");
    }
  }

  // Uses the OS share sheet where the browser exposes one and falls back to the
  // clipboard everywhere else — navigator.share is missing in most desktop
  // browsers, and a button that silently does nothing is worse than one that
  // copies.
  async function shareQuestion() {
    try {
      if (typeof navigator !== "undefined" && navigator.share) {
        await navigator.share({ text: question });
      } else {
        await writeTextToClipboard(question);
      }
      flash("share", "done");
    } catch (err) {
      // Dismissing the OS share sheet rejects with AbortError. That is a
      // cancellation, not a failure, so it must not flash red.
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        flash("share", "error");
      }
    }
  }

  // "Edit" refills the composer rather than rewriting history: every question
  // already carries a query_id and a durable audit chain, so silently replacing
  // a past turn would break the audit trail. The edited question is asked as a
  // new turn, and the original stays on the record.
  //
  // Refilling alone reads as a no-op, because the composer sits at the bottom
  // of a long conversation and is usually out of view — so scroll to it, put
  // the caret at the end of the restored text, and flash the button.
  function editQuestion() {
    if (!onEdit) return;
    onEdit();
    const box = document.querySelector<HTMLTextAreaElement>("[data-kriton-composer]");
    if (box) {
      box.scrollIntoView({ behavior: "smooth", block: "center" });
      // Deferred: the value lands on the next render, and focusing before that
      // would put the caret in a textarea that is still empty.
      window.setTimeout(() => {
        box.focus();
        box.setSelectionRange(box.value.length, box.value.length);
      }, 0);
    }
    flash("edit", "done");
  }

  const actions = [
    { key: "copy", label: "Copy message", icon: Copy, onClick: copyQuestion },
    { key: "share", label: "Share prompt", icon: Share2, onClick: shareQuestion },
    ...(onEdit ? [{ key: "edit", label: "Edit message", icon: PenLine, onClick: editQuestion }] : []),
  ];

  return (
    <div className="mt-1 flex items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
      {actions.map(({ key, label, icon: Icon, onClick }) => {
        const state = status[key] ?? "idle";
        return (
          <button
            key={key}
            type="button"
            onClick={onClick}
            title={label}
            aria-label={label}
            className={`rounded-md p-1.5 transition hover:bg-soft ${
              state === "error" ? "text-bad" : state === "done" ? "text-ok" : "text-muted hover:text-brand"
            }`}
          >
            {state === "done" ? <CheckCircle2 size={13} /> : <Icon size={13} />}
          </button>
        );
      })}
    </div>
  );
}

function ConversationTurn({
  turn,
  onFollowUp,
  onReuse,
}: {
  turn: Turn;
  onFollowUp?: (question: string, originalQuery: string) => void;
  onReuse?: (query: string) => void;
}) {
  const { submittedQuery, result, error, errorStatus, loading } = turn;
  const followUps = useMemo(() => getFollowUpSuggestions(result, submittedQuery), [result, submittedQuery]);
  const safety = result?.safety ?? null;
  const riskLevel = (safety?.risk_level ?? "LOW") as RiskLevel;
  const style = safety ? RISK_STYLES[riskLevel] : null;
  const route = result?.route ?? null;
  const outcome = result?.outcome ?? null;
  const outcomeStyle = outcome ? OUTCOME_STYLES[outcome] : null;
  const bundle = result?.source_bundle ?? null;
  const visibleLimitations = result?.answer?.limitations.filter(
    (l) => l !== "This response is for educational purposes only. Consult a qualified professional.",
  ) ?? [];
  const citationCount = result?.answer?.citations.length ?? 0;
  const routeLabel = route === "LLM"
    ? citationCount > 0
      ? "Answered — source grounded"
      : result?.visualization
        ? "Answered — structured from your input"
        : "Answered — no cited sources"
    : route === "CALCULATION"
      ? result?.calculation?.status === "clarification_required"
        ? "Clarification required — missing calculation input"
        : result?.calculation?.status === "undefined"
        ? "Calculation undefined — verified"
        : "Answered — calculated and verified"
      : ROUTE_LABELS[route ?? ""] ?? route;

  return (
    <>
      <div className="group flex flex-col items-end">
        {/* The documents this question was asked with, above the bubble and
            aligned with it. Shown per turn rather than only in the composer so
            a conversation scrolled back to weeks later still says which file an
            answer was grounded in — without it, an answer full of the client's
            own figures has no visible origin at all. */}
        {turn.attachments?.length ? (
          <div className="mb-1.5 flex max-w-[82%] flex-col items-end gap-1">
            {turn.attachments.map((attachment) => (
              <div
                key={attachment.documentId}
                className="flex max-w-full items-center gap-1.5 rounded-lg border border-line bg-soft/70 px-2.5 py-1 text-[11px] text-muted"
                title={attachment.name}
              >
                <FileText size={11} className="shrink-0" />
                <span className="min-w-0 truncate font-medium text-ink">{attachment.name}</span>
                {attachment.chunkCount ? (
                  <span className="shrink-0">
                    · {attachment.chunkCount} section{attachment.chunkCount === 1 ? "" : "s"}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}
        <div className="kriton-animate-msg-user kriton-user-query max-w-[82%] rounded-2xl rounded-tr-md border px-5 py-3 text-sm font-medium leading-6 text-ink shadow-sm">
          {submittedQuery}
        </div>
        <QuestionActions
          question={submittedQuery}
          onEdit={onReuse ? () => onReuse(submittedQuery) : undefined}
        />
      </div>

      {loading && <ThinkingIndicator message={turn.progressMessage} />}

      {!loading && error && (
        <div className="kriton-animate-msg-response min-w-0">
          <div className="rounded-2xl rounded-tl-md border border-bad/30 bg-bad/5 px-5 py-4 shadow-sm">
            {/* Names the real cause when the backend actually answered. The
                blanket "could not respond" is only honest for a transport
                failure, where there is no status to report. */}
            <p className="text-sm font-semibold text-bad">
              {errorStatus ? `Kriton returned an error (HTTP ${errorStatus})` : "Kriton could not respond"}
            </p>
            <p className="mt-1 text-xs text-bad/80">{error}</p>
          </div>
        </div>
      )}

      {result && safety && (
        <div className="kriton-animate-msg-response">
          <article className="min-w-0 w-full flex-1 py-1 text-ink">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <p className="text-sm font-bold text-ink">Kriton</p>
                  {outcomeStyle && <span className={`h-2 w-2 rounded-full ${outcomeStyle.dot}`} />}
                  {outcomeStyle && <span className={`text-xs font-semibold ${outcomeStyle.text}`}>{outcomeStyle.label}</span>}
                </div>
                <p className="mt-0.5 text-xs text-muted">{routeLabel}</p>
              </div>
              <div className="flex items-center gap-2">
                <Link
                  href={`/audit-replay?correlation_id=${encodeURIComponent(result.correlation_id)}`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-soft px-3 text-xs font-semibold text-ink hover:bg-line/40"
                >
                  <History size={13} />
                  View audit
                </Link>
              </div>
            </div>

            {result.effective_context && (
              <div className="mb-4 flex flex-wrap gap-x-3 gap-y-1 rounded-xl border border-line bg-soft/60 px-3 py-2 text-[11px] text-muted">
                <span className="font-bold text-ink">
                  {TASK_TYPES.find((task) => task.value === result.effective_context?.task_type)?.label ?? result.effective_context.task_type}
                </span>
                {result.effective_context.jurisdiction && <span>{result.effective_context.jurisdiction}</span>}
                {result.effective_context.framework && <span>{result.effective_context.framework.replaceAll("_", " ")}</span>}
                {result.effective_context.period_end && <span>Period end {result.effective_context.period_end}</span>}
                {result.effective_context.currency && <span>{result.effective_context.currency}</span>}
                <span>Context {result.context_decision?.status ?? "resolved"}</span>
              </div>
            )}

            <div className="kriton-animate-answer-reveal">
              {result.answer ? (
                <>
                  <AnswerRenderer
                    text={result.answer.text}
                    visualization={result.visualization}
                    secondaryVisualizations={result.secondary_visualizations}
                    calculationResult={result.answer.calculation_result}
                    verifiedCharts={result.answer.verified_charts}
                  />
                  {/* Citations render from the footer's "Sources" control (see
                      ResponseActions), not from a separate block here. */}
                  {visibleLimitations.length > 0 && (
                    <div className="mt-4 space-y-2 border-t border-line pt-4">
                      {visibleLimitations.map((l, i) => (
                        <div key={i} className="flex items-start gap-2 text-xs leading-5 text-muted">
                          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-warn" />
                          {l}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <p className="rounded-xl border border-line bg-soft p-4 text-sm italic leading-6 text-muted">
                  {outcome === "escalated"
                    ? "This query has been escalated for human review. No AI-generated response is returned until a qualified reviewer clears it."
                    : outcome === "clarification_required"
                      ? "Kriton needs more context to route this query correctly. Please respond to the clarification above."
                      : outcome === "rejected"
                        ? "This request was blocked before processing."
                        : "This query was refused by the policy engine. No response was composed."}
                </p>
              )}

              {result.next_action && (
                <div className="mt-4 rounded-xl border border-info/30 bg-info/5 p-3 text-sm leading-6 text-ink">
                  <span className="block text-[11px] font-bold uppercase text-info">{result.next_action.type}</span>
                  {result.next_action.message}
                </div>
              )}

              {result.answer && (
                <ResponseActions
                  question={submittedQuery}
                  result={result}
                  onReuse={onReuse ? () => onReuse(turn.query) : undefined}
                />
              )}

              <ExploreFurther
                questions={followUps}
                onFollowUp={onFollowUp ? (question) => onFollowUp(question, submittedQuery) : undefined}
              />
            </div>

            {bundle && (
              <p className="mt-4 border-t border-line pt-3 text-[11px] text-muted">
                {bundle.eligible_source_count} eligible
                {bundle.excluded_source_count > 0 ? ` · ${bundle.excluded_source_count} excluded` : ""} · {result.confidence_state.replaceAll("_", " ")} confidence
                {bundle.jurisdiction ? ` · ${bundle.jurisdiction}` : " · Any jurisdiction"} · {bundle.freshness_state} sources · {style?.label ?? "Unknown risk"}
              </p>
            )}
          </article>
        </div>
      )}
    </>
  );
}

export default function AskKritonPage() {
  const { session, loading: authLoading } = useAuth();
  const [query, setQuery] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [mode, setMode] = useState("Kriton's choice");
  const framework = "";
  const periodStart = "";
  const periodEnd = "";
  const currency = "";
  const [engagementId, setEngagementId] = useState("");
  const [attachments, setAttachments] = useState<AttachmentState[]>([]);
  const [documents, setDocuments] = useState<WorkspaceDocument[]>([]);
  // Only successfully indexed uploads are sent. A failed extraction has no
  // chunks behind it, so passing its id would add nothing but noise.
  const readyAttachments: TurnAttachment[] = attachments
    .filter((a) => a.status === "success" && a.documentId)
    .map((a) => ({ documentId: a.documentId as string, name: a.name, chunkCount: a.chunkCount }));
  const [submitting, setSubmitting] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>(() =>
    typeof window === "undefined" ? [] : loadConversations(),
  );
  const [activeId, setActiveIdState] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return loadActiveConversationId(loadConversations());
  });
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [sidebarPanel, setSidebarPanel] = useState<"projects" | "sources" | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  async function refreshDocuments() {
    const token = getAuthToken();
    if (!token) return;
    try {
      setDocuments(await listKritonAttachments(token, engagementId || undefined));
    } catch {
      // Upload remains available even when the saved-document library cannot load.
    }
  }

  // Load the saved-document library once signed in and whenever the engagement
  // scope changes, then re-attach the active conversation's documents so a
  // restored thread still shows what it was asked with. Fails soft: uploading
  // still works when the list cannot be fetched, the picker simply does not
  // appear. Uploads are covered by `onUploadComplete` instead.
  //
  // Keyed on the session token, not only on the engagement: getAuthToken()
  // reads a module-level cache that AuthContext fills asynchronously after
  // getSession() resolves, so on a fresh page load it is still "" during the
  // first render — waiting for an upload would leave the picker missing until
  // the user happened to attach something, which is exactly when they no
  // longer need it.
  useEffect(() => {
    if (authLoading) return;
    const token = session?.access_token;
    if (!token) return;
    let cancelled = false;
    void listKritonAttachments(token, engagementId || undefined).then((loadedDocuments) => {
      if (cancelled) return;
      setDocuments(loadedDocuments);
      const selectedIds = conversations.find((item) => item.id === activeId)?.documentIds ?? [];
      const restored = selectedIds
        .map((id) => loadedDocuments.find((item) => item.id === id && item.status === "READY"))
        .filter((item): item is WorkspaceDocument => Boolean(item))
        .map(attachmentFromDocument);
      if (restored.length > 0) {
        setAttachments(restored);
      }
    }).catch(() => {
      // Upload remains available even when the saved-document library cannot load.
    });
    return () => { cancelled = true; };
    // Reload when Supabase restores or changes the authenticated session, or
    // when the engagement scope changes; conversation changes are handled by
    // selectConversation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, session?.access_token, engagementId]);

  function setActiveId(id: string | null) {
    setActiveIdState(id);
    persistActiveConversationId(id);
  }

  function persist(next: Conversation[]) {
    setConversations(next);
    persistConversations(next);
  }

  function patchTurn(convId: string, turnId: string, patch: Partial<Turn>) {
    setConversations((prev) => {
      const next = prev.map((c) =>
        c.id !== convId ? c : { ...c, updatedAt: Date.now(), turns: c.turns.map((t) => (t.id !== turnId ? t : { ...t, ...patch })) },
      );
      persistConversations(next);
      return next;
    });
  }

  function startNewChat() {
    setActiveId(null);
    setQuery("");
    setAttachments([]);
  }

  /** Seeds the composer with the suggestion + the just-answered turn's own
   * question as context — never auto-submits, the user stays in control. */
  function handleFollowUp(question: string, originalTurnQuery: string) {
    setQuery(`${question} Context: ${originalTurnQuery}`);
  }

  function selectConversation(id: string) {
    setActiveId(id);
    setQuery("");
    const conversation = conversations.find((item) => item.id === id);
    setAttachments(
      (conversation?.documentIds ?? [])
        .map((documentId) => documents.find((item) => item.id === documentId))
        .filter((item): item is WorkspaceDocument => Boolean(item) && item!.status === "READY")
        .map(attachmentFromDocument),
    );
  }

  function pinConversation(id: string) {
    persist(conversations.map((c) => (c.id === id ? { ...c, pinned: !c.pinned } : c)));
  }

  function renameConversation(id: string, title: string) {
    persist(conversations.map((c) => (c.id === id ? { ...c, title } : c)));
  }

  /** Export any thread from the sidebar, not just the one currently open —
   * looked up by id rather than using activeConversation, so downloading an
   * old chat does not require switching to it first. */
  function downloadConversation(id: string) {
    const conversation = conversations.find((c) => c.id === id);
    if (!conversation) return;
    downloadTextFile(
      conversationAsMarkdown(conversation),
      safeDownloadName(conversation.title || "kriton-chat", "md"),
    );
  }

  function deleteConversation(id: string) {
    persist(conversations.filter((c) => c.id !== id));
    if (activeId === id) {
      setActiveId(null);
      // The active composer's pending selection no longer has a conversation.
      setAttachments([]);
    }
  }

  async function handleSubmit() {
    const trimmed = query.trim();
    if (!trimmed || submitting) return;
    const token = getAuthToken();
    if (!token) {
      setSubmitError("Please sign in before asking Kriton.");
      return;
    }

    const turnId = genId("turn");
    const isNew = activeId === null;
    const convId = activeId ?? genId("conv");
    const now = timestamp();
    const priorConversation = conversations.find((c) => c.id === convId) ?? null;
    const previousQuery = priorConversation?.turns.at(-1)?.submittedQuery.trim() || undefined;
    const cycle = clarificationCycleFor(priorConversation);

    // Snapshot only the documents currently visible in the composer. Previous
    // turns retain their attachment metadata for display and audit, but must
    // never repopulate a later request implicitly. De-duplicate defensively in
    // case the same document entered through both upload and library selection.
    const turnAttachments: TurnAttachment[] = readyAttachments.filter(
      (attachment, index, selected) =>
        selected.findIndex((candidate) => candidate.documentId === attachment.documentId) === index,
    );
    const documentIds = turnAttachments.map((attachment) => attachment.documentId);

    const newTurn: Turn = {
      id: turnId, query: trimmed, submittedQuery: trimmed,
      result: null, error: null, loading: true,
      attachments: turnAttachments.length ? turnAttachments : undefined,
    };
    setConversations((prev) => {
      const next = isNew
        ? [{ id: convId, title: trimmed.slice(0, 80), turns: [newTurn], createdAt: now, updatedAt: now, pinned: false, documentIds }, ...prev]
        : prev.map((c) => (c.id === convId ? { ...c, updatedAt: now, documentIds, turns: [...c.turns, newTurn] } : c));
      persistConversations(next);
      return next;
    });
    if (isNew) {
      setActiveId(convId);
    }

    setQuery("");
    // The submitted attachments are captured on the turn above. Clear only the
    // composer selection so the sent query and files no longer remain in the
    // input box while the response is loading.
    setAttachments([]);
    setSubmitError(null);
    setSubmitting(true);
    try {
      const idempotencyKey = genId("idem");
      const response = await askKritonStream(
        token,
        {
          query: trimmed,
          previous_query: previousQuery,
          jurisdiction,
          mode,
          clarification_cycle: cycle,
          conversation_id: convId,
          document_ids: documentIds,
          // An attached file defines the entity/source scope for this chat.
          // Do not silently replace a document miss with same-name web results
          // (for example, another company called "Apex").
          source_scope: documentIds.length ? "DOCUMENTS_ONLY" : "WEB_ONLY",
          task_context: {
            engagement_id: engagementId || null,
            jurisdiction: jurisdiction || null,
            framework: framework || null,
            period_start: periodStart || null,
            period_end: periodEnd || null,
            currency: currency || null,
            language: "en",
            intended_use: "research",
          },
        },
        idempotencyKey,
        ({ message }) => patchTurn(convId, turnId, { progressMessage: message }),
      );
      patchTurn(convId, turnId, { result: response, loading: false });
    } catch (err) {
      patchTurn(convId, turnId, {
        error: err instanceof ApiError ? err.message : "Could not reach the orchestration service.",
        errorStatus: err instanceof ApiError ? err.status : null,
        loading: false,
      });
    } finally {
      setSubmitting(false);
    }
  }

  const [submitError, setSubmitError] = useState<string | null>(null);

  const activeConversation = conversations.find((c) => c.id === activeId) ?? null;
  const hasConversation = activeConversation !== null && activeConversation.turns.length > 0;
  const sorted = useMemo(() => sortConversations(conversations), [conversations]);
  const conversationSources = useMemo(() => {
    const unique = new Map<string, SourceCitation>();
    for (const conversation of conversations) {
      for (const turn of conversation.turns) {
        for (const citation of turn.result?.answer?.citations ?? []) {
          unique.set(citation.url || `${citation.ref_id}:${citation.title}`, citation);
        }
      }
    }
    return [...unique.values()];
  }, [conversations]);
  const lastTurnLoading = activeConversation?.turns.at(-1)?.loading;
  const turnCount = activeConversation?.turns.length;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turnCount, lastTurnLoading]);

  useEffect(() => {
    const token = session?.access_token;
    if (!token) return;
    let cancelled = false;
    listEngagements(token)
      .then((items) => {
        if (!cancelled) {
          setEngagementId((current) => current || (items.length === 1 ? items[0].id : ""));
        }
      })
      .catch(() => {
        // No automatic engagement scope is available. The backend will ask a
        // targeted clarification if protected work requires one.
      });
    return () => { cancelled = true; };
  }, [session?.access_token]);

  const sidebarProps = {
    conversations: sorted,
    activeId,
    onSelect: selectConversation,
    onPin: pinConversation,
    onRename: renameConversation,
    onDownload: downloadConversation,
    onDelete: deleteConversation,
    onNewChat: startNewChat,
    onOpenProjects: () => setSidebarPanel("projects"),
    onOpenSources: () => setSidebarPanel("sources"),
  };

  return (
    <main className="kriton-page-background relative min-h-screen w-full min-w-0 overflow-hidden text-ink">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-soft" />
      <div className="relative z-10 grid h-screen w-full min-w-0 grid-cols-1 md:grid-cols-[252px_minmax(0,1fr)]">
        <DesktopSidebar {...sidebarProps} showMenu />
        <MobileDrawer {...sidebarProps} showMenu open={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} />

        <section className="relative flex min-h-0 min-w-0 flex-col">
          <header className="relative z-10 flex h-14 items-center justify-between border-b border-line bg-panel/80 px-4 md:hidden">
            <div className="flex items-center gap-2">
              <ZoikoGlyph className="h-8 w-8 rounded-lg" />
              <span className="font-bold text-ink">Kriton</span>
            </div>
            <button onClick={() => setMobileMenuOpen(true)} aria-label="Open recent chats" className="text-muted">
              <History size={19} />
            </button>
          </header>

          {sidebarPanel === "projects" && (
            <KritonPanel
              title="Projects"
              description="Continue your Kriton work without leaving the assistant."
              onClose={() => setSidebarPanel(null)}
            >
              {sorted.length === 0 ? (
                <p className="text-sm text-muted">No project conversations yet. Start a new chat to create your first one.</p>
              ) : (
                <div className="space-y-2">
                  {sorted.map((conversation) => (
                    <button
                      key={conversation.id}
                      type="button"
                      onClick={() => { selectConversation(conversation.id); setSidebarPanel(null); }}
                      className="flex w-full items-center justify-between gap-4 rounded-xl border border-line p-3 text-left hover:border-brand/30 hover:bg-soft"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold text-ink">{conversation.title}</span>
                        <span className="mt-0.5 block text-xs text-muted">{conversation.turns.length} exchange{conversation.turns.length === 1 ? "" : "s"}</span>
                      </span>
                      <FolderKanban size={17} className="shrink-0 text-brand" />
                    </button>
                  ))}
                </div>
              )}
            </KritonPanel>
          )}

          {sidebarPanel === "sources" && (
            <KritonPanel
              title="Sources"
              description="Sources cited across your Kriton conversations."
              onClose={() => setSidebarPanel(null)}
            >
              {conversationSources.length === 0 ? (
                <p className="text-sm text-muted">No cited sources yet. Sources used in answers will appear here.</p>
              ) : (
                <div className="space-y-1">
                  {conversationSources.map((citation) => (
                    <SourceButton key={citation.url || `${citation.ref_id}:${citation.title}`} citation={citation} />
                  ))}
                </div>
              )}
            </KritonPanel>
          )}

          <div ref={scrollRef} className="relative z-10 min-w-0 flex-1 overflow-y-auto px-4">
            <div className="mx-auto flex min-h-full min-w-0 w-full max-w-5xl flex-col items-center justify-center pb-16 pt-6 md:pb-24 md:pt-8">
              {!hasConversation ? (
                <div className="flex w-full max-w-3xl flex-col items-center text-center">
                  <div className="w-full">
                    <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-line bg-panel px-3 py-1 text-xs font-bold uppercase tracking-[0.18em] text-brand shadow-sm">
                      <Sparkles size={14} />
                      Ask Kriton
                    </div>
                    <h1 className="text-balance text-4xl font-bold tracking-normal text-ink md:text-5xl">
                      Get a governed answer from your sources.
                    </h1>
                    <p className="mx-auto mt-4 max-w-2xl text-sm leading-6 text-muted">
                      Ask accounting, audit, and policy questions with source checks, risk routing, and audit history kept in the flow.
                    </p>
                  </div>

                  <div className="mt-8 w-full">
                    <Composer
                      variant="hero"
                      query={query}
                      onQueryChange={setQuery}
                      onSubmit={handleSubmit}
                      attachments={attachments}
                      onAttachmentsChange={setAttachments}
                      documents={documents}
                      onUploadComplete={refreshDocuments}
                      engagementId={engagementId || undefined}
                      jurisdiction={jurisdiction}
                      onJurisdictionChange={setJurisdiction}
                      submitting={submitting}
                      error={submitError}
                    />
                  </div>

                  <div className="mt-5 grid w-full grid-cols-2 gap-2 md:grid-cols-5">
                    {QUICK_MODES.map(({ label, icon: ModeIcon, prompt }) => (
                      <button
                        key={label}
                        type="button"
                        onClick={() => {
                          setMode(label);
                          setQuery((current) => `${prompt}${current}`.trim());
                        }}
                        className={`inline-flex h-10 items-center justify-center gap-2 rounded-xl border px-2 text-xs font-bold shadow-sm transition ${mode === label ? "border-brand/40 bg-brand/10 text-brand" : "border-line bg-panel text-ink hover:border-brand/30 hover:bg-soft"}`}
                      >
                        <ModeIcon size={16} />
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="w-full min-w-0 max-w-3xl space-y-6 self-stretch md:translate-x-14 lg:translate-x-24">
                  {activeConversation?.turns.map((turn) => (
                    <div key={turn.id} className="min-w-0 space-y-6 border-b border-line/70 pb-7 last:border-b-0">
                      <ConversationTurn turn={turn} onFollowUp={handleFollowUp} onReuse={setQuery} />
                    </div>
                  ))}

                  <Composer
                    variant="sticky"
                    query={query}
                    onQueryChange={setQuery}
                    jurisdiction={jurisdiction}
                    onJurisdictionChange={setJurisdiction}
                    onSubmit={handleSubmit}
                    attachments={attachments}
                    onAttachmentsChange={setAttachments}
                    documents={documents}
                    onUploadComplete={refreshDocuments}
                    engagementId={engagementId || undefined}
                    submitting={submitting}
                    error={submitError}
                  />
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
