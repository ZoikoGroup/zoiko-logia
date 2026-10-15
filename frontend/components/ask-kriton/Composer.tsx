"use client";

import { useEffect, useRef, useState, type Dispatch, type KeyboardEvent, type SetStateAction } from "react";
import {
  AlertTriangle,
  ArrowUp,
  CheckCircle2,
  FileText,
  Loader2,
  Mic,
  Paperclip,
  Plus,
  X,
} from "lucide-react";
import { getAuthToken, getKritonAttachment, uploadKritonAttachment, deleteKritonAttachment, ApiError, type WorkspaceDocument } from "@/lib/api";

const JURISDICTIONS = ["", "UK", "US", "US-CA", "IFRS", "UAE", "India", "EU"];
const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".txt", ".md"];

// Retrieval ranks chunks across every attached document, so a very wide
// selection dilutes the ranking rather than improving it — and each file is
// parsed and chunked server-side before the turn can run.
const MAX_ATTACHMENTS = 10;
// Matches the server-side limit, so an oversized file is reported instantly
// instead of after a full upload that is bound to be rejected.
const MAX_FILE_BYTES = 20 * 1024 * 1024;
function formatSize(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
// Uploads run concurrently so several files don't queue behind each other,
// but not unboundedly: each one is a multipart POST that parses and indexes
// server-side, and the browser caps parallel connections per origin anyway.
const UPLOAD_CONCURRENCY = 3;

export type AttachmentState = {
  // Client-side identity, assigned before the upload starts. The document id
  // only exists once the server responds, and filenames repeat — neither
  // works as a React key or as the handle for progress updates.
  id: string;
  documentId?: string;
  name: string;
  status: "uploading" | "processing" | "success" | "error";
  progress: number;
  chunkCount?: number;
  error?: string;
  /** Set when the entry refers to a document that was already indexed in this
   *  workspace (picked from the library, or restored with a saved conversation)
   *  rather than uploaded through this composer. Removing such an entry means
   *  "not for this question", never "delete it". */
  fromLibrary?: boolean;
};

let attachmentCounter = 0;
export function nextAttachmentId(): string {
  attachmentCounter += 1;
  return `att-${Date.now().toString(36)}-${attachmentCounter}`;
}

/** An already-uploaded document, shaped as a composer attachment. Used when
 * restoring a conversation's documents, so restored and freshly-uploaded
 * entries are indistinguishable to the rest of the component. */
export function attachmentFromDocument(document: WorkspaceDocument): AttachmentState {
  return {
    id: nextAttachmentId(),
    documentId: document.id,
    name: document.filename,
    status: document.status === "READY" ? "success" : "error",
    progress: 1,
    chunkCount: document.chunk_count,
    error: document.processing_error ?? undefined,
    fromLibrary: true,
  };
}

export function isAttachmentPending(attachment: AttachmentState): boolean {
  return attachment.status === "uploading" || attachment.status === "processing";
}

/** Run `worker` over `items` with at most `limit` in flight at once. */
async function mapWithConcurrency<T>(items: T[], limit: number, worker: (item: T) => Promise<void>): Promise<void> {
  let cursor = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      await worker(items[index]);
    }
  });
  await Promise.all(runners);
}

const wait = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function waitUntilReady(token: string, documentId: string): Promise<WorkspaceDocument> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const document = await getKritonAttachment(token, documentId);
    if (document.status === "READY") return document;
    if (document.status === "FAILED") {
      throw new ApiError(422, document.processing_error ?? "The document could not be processed.");
    }
    await wait(1000);
  }
  throw new ApiError(408, "Document processing is taking longer than expected. Select it again when it becomes ready.");
}

// Minimal ambient shape for the (non-standard) Web Speech API — no @types
// package ships one, and most of its surface is unused here.
type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function getSpeechRecognition(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function Composer({
  variant,
  query,
  onQueryChange,
  onSubmit,
  attachments,
  onAttachmentsChange,
  documents,
  onUploadComplete,
  engagementId,
  submitting,
  error,
  jurisdiction,
  onJurisdictionChange,
}: {
  variant: "hero" | "sticky";
  query: string;
  onQueryChange: (value: string) => void;
  onSubmit: () => void;
  /** Attachment list, owned by the page.
   *
   *  This deliberately does NOT live in local state. The page renders a "hero"
   *  Composer before a conversation exists and a "sticky" one afterwards, so
   *  asking the first question unmounts one instance and mounts the other. With
   *  the list held locally, the file the user had just attached vanished at
   *  exactly that moment — the chip disappeared and the ids never reached the
   *  request, so the answer came back grounded only in web sources. Holding it
   *  one level up lets the selection survive that swap; the page clears it as
   *  soon as the current question is submitted. */
  attachments: AttachmentState[];
  onAttachmentsChange: Dispatch<SetStateAction<AttachmentState[]>>;
  /** Documents already uploaded in this workspace, for the "Add saved
   *  document" picker. Fetched and owned by the page, since it also refreshes
   *  the list after an upload. */
  documents: WorkspaceDocument[];
  onUploadComplete: () => void;
  /** Scopes uploads and the document library to the selected engagement. */
  engagementId?: string;
  submitting: boolean;
  error: string | null;
  jurisdiction: string;
  onJurisdictionChange: (value: string) => void;
}) {
  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  // The "+" menu of the compact (in-conversation) composer.
  const [plusOpen, setPlusOpen] = useState(false);
  const plusRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!plusOpen) return;
    function close(event: MouseEvent) {
      if (!plusRef.current?.contains(event.target as Node)) setPlusOpen(false);
    }
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") setPlusOpen(false);
    }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", onKey); };
  }, [plusOpen]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 220)}px`;
  }, [query]);

  const pending = attachments.some(isAttachmentPending);
  const readyDocumentIds = attachments
    .filter((item) => item.status === "success" && item.documentId)
    .map((item) => item.documentId as string);

  function patchAttachment(id: string, patch: Partial<AttachmentState>) {
    onAttachmentsChange((previous) => previous.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (pending) return;
      onSubmit();
    }
  }

  async function uploadOne(entry: { id: string; file: File }) {
    const token = getAuthToken();
    if (!token) {
      patchAttachment(entry.id, { status: "error", progress: 0, error: "Please sign in before uploading." });
      return;
    }
    try {
      const result = await uploadKritonAttachment(
        token,
        entry.file,
        (fraction) => {
          // Upload progress only reaches 100% when the bytes have arrived;
          // extraction happens after that, so the bar is capped at 95% until
          // the response lands. Showing 100% while the server is still parsing
          // would read as "done" for several more seconds.
          patchAttachment(entry.id, { progress: Math.min(fraction, 0.95) });
        },
        engagementId,
      );
      if (result.status === "READY") {
        patchAttachment(entry.id, { documentId: result.document_id, status: "success", progress: 1, chunkCount: result.chunk_count });
      } else {
        patchAttachment(entry.id, { documentId: result.document_id, status: "processing", progress: 1, chunkCount: 0 });
        const ready = await waitUntilReady(token, result.document_id);
        patchAttachment(entry.id, { documentId: ready.id, name: ready.filename, status: "success", progress: 1, chunkCount: ready.chunk_count });
      }
    } catch (err) {
      // Scoped to this file: one rejected or oversized document must not
      // discard the others that uploaded cleanly alongside it.
      patchAttachment(entry.id, { status: "error", progress: 0, error: err instanceof ApiError ? err.message : "Upload failed." });
    }
  }

  async function handleFilesSelected(files: File[]) {
    if (files.length === 0) return;

    const room = MAX_ATTACHMENTS - attachments.length;
    if (room <= 0) {
      onAttachmentsChange((previous) => [
        ...previous,
        { id: nextAttachmentId(), name: `${files.length} more file${files.length === 1 ? "" : "s"}`, status: "error", progress: 0, error: `Limit reached — up to ${MAX_ATTACHMENTS} documents per question.` },
      ]);
      return;
    }

    const accepted = files.slice(0, room);
    const overflow = files.slice(room);
    const queued: { id: string; file: File }[] = [];
    const added: AttachmentState[] = [];

    for (const file of accepted) {
      const id = nextAttachmentId();
      const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
      if (!ACCEPTED_EXTENSIONS.includes(ext)) {
        added.push({ id, name: file.name, status: "error", progress: 0, error: `Unsupported file type — allowed: ${ACCEPTED_EXTENSIONS.join(", ")}` });
        continue;
      }
      if (file.size === 0) {
        added.push({ id, name: file.name, status: "error", progress: 0, error: "This file is empty" });
        continue;
      }
      if (file.size > MAX_FILE_BYTES) {
        added.push({ id, name: file.name, status: "error", progress: 0, error: `${formatSize(file.size)} — over the 20 MB limit` });
        continue;
      }
      added.push({ id, name: file.name, status: "uploading", progress: 0 });
      queued.push({ id, file });
    }
    if (overflow.length > 0) {
      added.push({ id: nextAttachmentId(), name: `${overflow.length} more file${overflow.length === 1 ? "" : "s"} not attached`, status: "error", progress: 0, error: `Limit reached — up to ${MAX_ATTACHMENTS} documents per question.` });
    }

    onAttachmentsChange((previous) => [...previous, ...added]);
    await mapWithConcurrency(queued, UPLOAD_CONCURRENCY, uploadOne);
    // Refresh the saved-document library once, after the whole batch, rather
    // than re-fetching it per file.
    onUploadComplete();
  }

  async function removeAttachment(attachment: AttachmentState) {
    onAttachmentsChange((previous) => previous.filter((entry) => entry.id !== attachment.id));
    // Also drop the indexed copy — leaving chunks behind for a document the
    // user has visibly removed would keep influencing answers.
    //
    // Except for one that was already indexed before this composer saw it:
    // there, removing it means "not for this question", not "delete it".
    // Deleting would destroy a stored document the user never asked to lose,
    // and take it out of every other conversation that cites it.
    if (attachment.fromLibrary) return;
    const token = getAuthToken();
    if (token && attachment.documentId) {
      try {
        await deleteKritonAttachment(token, attachment.documentId, engagementId);
      } catch {
        /* The row is orphaned but unreachable from the UI; not worth alarming
           the user, who has already seen the attachment disappear. */
      }
    }
  }

  // What each Web Speech API error means for the person at the keyboard.
  const VOICE_ERRORS: Record<string, string> = {
    "not-allowed": "Microphone access is blocked. Allow it from the icon at the left of the address bar, then try again.",
    "service-not-allowed": "This browser does not allow speech recognition here. Try Chrome or Edge.",
    "audio-capture": "No microphone was found. Check one is connected and selected.",
    network: "The browser's speech service could not be reached. Check your internet connection.",
    "no-speech": "Nothing was heard. Press the mic and start speaking.",
    "language-not-supported": "Speech recognition does not support your browser language. Try English.",
  };

  async function toggleVoice() {
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    const Recognition = getSpeechRecognition();
    if (!Recognition) {
      setVoiceError("Voice input is not supported in this browser. Use Chrome, Edge or Safari.");
      return;
    }
    setVoiceError(null);
    // Ask for the microphone first, so the browser shows its permission
    // prompt and a refusal can be explained instead of failing silently.
    if (navigator.mediaDevices?.getUserMedia) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((track) => track.stop());
      } catch (err) {
        const name = err instanceof DOMException ? err.name : "";
        setVoiceError(name === "NotFoundError" ? VOICE_ERRORS["audio-capture"] : VOICE_ERRORS["not-allowed"]);
        return;
      }
    }
    const recognition = new Recognition();
    recognition.continuous = false;
    // Interim results show the words as they are spoken.
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-GB";
    const before = query.trim();
    recognition.onresult = (e) => {
      const spoken = Array.from(e.results).map((result) => result[0]?.transcript ?? "").join(" ").trim();
      onQueryChange(`${before}${before && spoken ? " " : ""}${spoken}`);
    };
    recognition.onerror = (e) => {
      setListening(false);
      if (e.error !== "aborted") setVoiceError(VOICE_ERRORS[e.error] ?? `Voice input stopped (${e.error}). Try again.`);
    };
    recognition.onend = () => {
      setListening(false);
      textareaRef.current?.focus();
    };
    recognitionRef.current = recognition;
    try {
      recognition.start();
      setListening(true);
    } catch {
      setVoiceError("Voice input could not start. Try again.");
    }
  }

  // Stop listening if the composer goes away mid-dictation.
  useEffect(() => () => recognitionRef.current?.stop(), []);

  const savedDocuments = documents
    .filter((document) => document.status === "READY")
    .filter((document) => !attachments.some((entry) => entry.documentId === document.id));

  function addSavedDocument(documentId: string) {
    const document = documents.find((item) => item.id === documentId);
    if (!document) return;
    onAttachmentsChange((previous) => (
      previous.some((entry) => entry.documentId === document.id)
        ? previous
        : [...previous, {
            id: nextAttachmentId(),
            documentId: document.id,
            name: document.filename,
            status: document.status === "READY" ? "success" : "error",
            progress: 1,
            chunkCount: document.chunk_count,
            error: document.processing_error ?? undefined,
            fromLibrary: true,
          }]
    ));
  }

  const uploadLabel = (() => {
    const uploading = attachments.filter((item) => item.status === "uploading");
    if (uploading.length > 0) {
      const mean = uploading.reduce((total, item) => total + item.progress, 0) / uploading.length;
      return uploading.length > 1
        ? `Uploading ${uploading.length} files ${Math.round(mean * 100)}%`
        : `Uploading ${Math.round(mean * 100)}%`;
    }
    return "Processing…";
  })();

  const fileInput = (
    <input
      ref={fileInputRef}
      type="file"
      multiple
      accept={ACCEPTED_EXTENSIONS.join(",")}
      className="hidden"
      onChange={(e) => {
        const files = Array.from(e.target.files ?? []);
        if (files.length > 0) void handleFilesSelected(files);
        // Reset so re-picking the same file still fires onChange.
        e.target.value = "";
      }}
    />
  );

  const attachmentList = attachments.length > 0 && (
    <div className="mb-3 space-y-1.5">
      {attachments.length > 1 && (
        <div className="flex items-center justify-between px-1 text-[11px] font-semibold text-muted">
          <span>
            {readyDocumentIds.length} of {attachments.length} document{attachments.length === 1 ? "" : "s"} ready
          </span>
          <button
            type="button"
            onClick={() => onAttachmentsChange([])}
            className="rounded px-1 py-0.5 font-semibold text-muted transition hover:bg-soft hover:text-ink"
          >
            Remove all
          </button>
        </div>
      )}
      {attachments.map((item) => (
        <div key={item.id} className="flex items-center gap-2 rounded-xl border border-line bg-soft/60 px-3 py-2 text-xs">
          {isAttachmentPending(item) && <Loader2 size={14} className="shrink-0 animate-spin text-brand" />}
          {item.status === "success" && <CheckCircle2 size={14} className="shrink-0 text-ok" />}
          {item.status === "error" && <AlertTriangle size={14} className="shrink-0 text-bad" />}
          <FileText size={14} className="shrink-0 text-muted" />
          <span className="min-w-0 flex-1 truncate font-medium text-ink">{item.name}</span>
          {item.status === "success" && <span className="shrink-0 text-ok">Used in this chat</span>}
          <span className="shrink-0 text-muted">
            {item.status === "uploading" && `${Math.round(item.progress * 100)}%`}
            {item.status === "processing" && "Processing…"}
            {item.status === "success" && `${item.chunkCount} chunks`}
            {item.status === "error" && item.error}
          </span>
          <button
            type="button"
            onClick={() => void removeAttachment(item)}
            aria-label={`Remove ${item.name}`}
            className="shrink-0 rounded p-0.5 text-muted hover:bg-soft"
          >
            <X size={13} />
          </button>
        </div>
      ))}
    </div>
  );

  const textarea = (rowsShown: number, className: string) => (
    <textarea
      ref={textareaRef}
      value={query}
      onChange={(e) => onQueryChange(e.target.value)}
      onKeyDown={handleKeyDown}
      placeholder={variant === "hero" ? "Ask Kriton..." : "Ask a follow-up..."}
      rows={rowsShown}
      aria-label={variant === "hero" ? "Ask Kriton" : "Ask a follow-up"}
      className={`max-h-[min(220px,30dvh)] w-full resize-none overflow-y-auto overscroll-contain !border-transparent !bg-transparent text-ink !shadow-none outline-none placeholder:text-muted ${className}`}
    />
  );

  const jurisdictionSelect = (className: string) => (
    <select
      aria-label="Jurisdiction"
      value={jurisdiction}
      onChange={(event) => onJurisdictionChange(event.target.value)}
      className={`h-9 rounded-full !border-transparent !bg-soft px-3 text-xs font-semibold text-ink !shadow-none outline-none hover:bg-line/40 ${className}`}
    >
      {JURISDICTIONS.map((value) => (
        <option key={value || "any"} value={value}>{value || "Any jurisdiction"}</option>
      ))}
    </select>
  );

  const micButton = (
    <button
      type="button"
      onClick={toggleVoice}
      aria-label={listening ? "Stop voice input" : "Voice input"}
      title={voiceError ?? (listening ? "Stop voice input" : "Voice input")}
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition ${
        listening ? "animate-pulse bg-bad/10 text-bad" : "text-muted hover:bg-soft hover:text-ink"
      }`}
    >
      <Mic size={19} />
    </button>
  );

  const sendButton = (
    <button
      type="submit"
      disabled={submitting || !query.trim() || pending}
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand text-white transition hover:bg-brand-2 disabled:opacity-40"
      aria-label={variant === "hero" ? "Ask Kriton" : "Ask follow-up"}
      title="Send"
    >
      {submitting ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={17} />}
    </button>
  );

  const submitForm = (e: React.FormEvent) => {
    e.preventDefault();
    if (pending) return;
    onSubmit();
  };

  const messages = (
    <>
      {voiceError && <p className="mt-2 text-center text-xs text-muted">{voiceError}</p>}
      {error && (
        <div className="mt-3 rounded-xl border border-bad/30 bg-bad/5 px-4 py-2.5 text-sm text-bad" role="alert">
          {error}
        </div>
      )}
    </>
  );

  // In the conversation: one slim rounded bar — "+" menu, the text, then
  // jurisdiction, voice and a round send button — like a chat app's composer.
  if (variant === "sticky") {
    return (
      <div>
        <form onSubmit={submitForm} data-kriton-composer className="mx-auto w-full max-w-3xl">
          {attachmentList}
          <div className="kriton-composer-surface flex items-end gap-1.5 rounded-[1.75rem] border px-2 py-1.5 shadow-[0_8px_28px_rgba(18,34,32,0.08)]">
            {fileInput}
            <div ref={plusRef} className="relative shrink-0">
              <button
                type="button"
                onClick={() => setPlusOpen((open) => !open)}
                aria-label="Add documents"
                aria-haspopup="menu"
                aria-expanded={plusOpen}
                title="Add documents"
                className="flex h-9 w-9 items-center justify-center rounded-full text-ink transition hover:bg-soft"
              >
                {pending ? <Loader2 size={18} className="animate-spin text-brand" /> : <Plus size={20} />}
              </button>
              {plusOpen && (
                <div role="menu" className="absolute bottom-full left-0 z-30 mb-2 w-64 overflow-hidden rounded-xl border border-line bg-panel py-1 shadow-xl">
                  <button
                    type="button"
                    role="menuitem"
                    disabled={attachments.length >= MAX_ATTACHMENTS}
                    onClick={() => { setPlusOpen(false); fileInputRef.current?.click(); }}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-ink hover:bg-soft disabled:opacity-50"
                  >
                    <Paperclip size={15} className="text-muted" /> Upload documents
                  </button>
                  {savedDocuments.length > 0 && (
                    <>
                      <div className="mt-1 border-t border-line px-3 pb-1 pt-2 text-[10px] font-bold uppercase tracking-wider text-muted">Saved documents</div>
                      <div className="max-h-48 overflow-y-auto">
                        {savedDocuments.map((document) => (
                          <button
                            key={document.id}
                            type="button"
                            role="menuitem"
                            disabled={attachments.length >= MAX_ATTACHMENTS}
                            onClick={() => { addSavedDocument(document.id); setPlusOpen(false); }}
                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-ink hover:bg-soft disabled:opacity-50"
                          >
                            <FileText size={15} className="shrink-0 text-muted" />
                            <span className="truncate">{document.filename}</span>
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
            <div className="min-w-0 flex-1 py-1.5">
              {pending && <span className="sr-only" role="status">{uploadLabel}</span>}
              {textarea(1, "min-h-6 px-1 text-[15px] leading-6")}
            </div>
            {jurisdictionSelect("hidden sm:block")}
            {micButton}
            {sendButton}
          </div>
          <p className="mt-1.5 text-center text-[11px] text-muted">
            Kriton checks answers against sources, but can still make mistakes. Verify important figures.
          </p>
        </form>
        {messages}
      </div>
    );
  }

  return (
    <div>
      <form onSubmit={submitForm} data-kriton-composer className="mt-8 w-full">
        <div className="kriton-composer-surface rounded-[1.75rem] border p-4 shadow-[0_18px_48px_rgba(18,34,32,0.08)]">
          {attachmentList}
          {textarea(2, "min-h-20 rounded-xl px-1 py-1 text-base font-medium leading-7")}

          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              {fileInput}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={attachments.length >= MAX_ATTACHMENTS}
                aria-label="Attach documents"
                className="inline-flex h-9 items-center justify-center gap-2 rounded-full bg-soft px-2.5 text-xs font-semibold text-ink transition hover:bg-line/60 disabled:cursor-not-allowed disabled:opacity-50 sm:px-3"
              >
                {pending ? (
                  <>
                    <Loader2 size={16} className="shrink-0 animate-spin" />
                    <span className="hidden sm:inline">{uploadLabel}</span>
                  </>
                ) : (
                  <>
                    <Paperclip size={16} className="shrink-0" />
                    <span className="hidden sm:inline">
                      {attachments.length > 0 ? "Add documents" : "Attach documents"}
                    </span>
                  </>
                )}
              </button>
              {documents.length > 0 && (
                <select
                  aria-label="Add a saved document"
                  // Always reads "Saved documents": picking one ADDS it to the
                  // selection rather than replacing it, so the control is an
                  // action list, not a display of current state. What is
                  // currently attached is shown by the chips above.
                  value=""
                  disabled={attachments.length >= MAX_ATTACHMENTS}
                  onChange={(event) => addSavedDocument(event.target.value)}
                  className="h-9 max-w-48 rounded-full !border-transparent !bg-soft px-3 text-xs font-semibold text-ink outline-none disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="">Saved documents</option>
                  {savedDocuments.map((document) => (
                    <option key={document.id} value={document.id}>{document.filename}</option>
                  ))}
                </select>
              )}
            </div>

            <div className="flex min-w-0 items-center justify-end gap-2">
              {jurisdictionSelect("hidden sm:block")}
              {micButton}
              {sendButton}
            </div>
          </div>
        </div>
      </form>
      {messages}
    </div>
  );
}
