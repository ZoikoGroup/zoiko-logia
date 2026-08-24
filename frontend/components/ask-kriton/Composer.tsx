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
  X,
} from "lucide-react";
import { getAuthToken, getKritonAttachment, uploadKritonAttachment, ApiError, type WorkspaceDocument } from "@/lib/api";

const JURISDICTIONS = ["", "UK", "US", "US-CA", "IFRS", "UAE", "India", "EU"];
const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".xlsx", ".pptx"];

// Retrieval ranks chunks across every attached document, so a very wide
// selection dilutes the ranking rather than improving it — and each file is
// parsed and chunked server-side before the turn can run.
const MAX_ATTACHMENTS = 10;
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
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: (() => void) | null;
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
  jurisdiction,
  onJurisdictionChange,
  onSubmit,
  attachments,
  onAttachmentsChange,
  documents,
  onUploadComplete,
  submitting,
  error,
}: {
  variant: "hero" | "sticky";
  query: string;
  onQueryChange: (value: string) => void;
  jurisdiction: string;
  onJurisdictionChange: (value: string) => void;
  onSubmit: (documentIds?: string[]) => void;
  attachments: AttachmentState[];
  onAttachmentsChange: Dispatch<SetStateAction<AttachmentState[]>>;
  documents: WorkspaceDocument[];
  onUploadComplete: () => void;
  submitting: boolean;
  error: string | null;
}) {
  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

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
      onSubmit(readyDocumentIds);
    }
  }

  async function uploadOne(entry: { id: string; file: File }) {
    const token = getAuthToken();
    if (!token) {
      patchAttachment(entry.id, { status: "error", progress: 0, error: "Please sign in before uploading." });
      return;
    }
    try {
      const result = await uploadKritonAttachment(token, entry.file, (fraction) => {
        patchAttachment(entry.id, { progress: fraction });
      });
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

  function toggleVoice() {
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    const Recognition = getSpeechRecognition();
    if (!Recognition) {
      setVoiceError("Voice input is not supported in this browser.");
      return;
    }
    setVoiceError(null);
    const recognition = new Recognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";
    recognition.onresult = (e) => {
      const transcript = Array.from(e.results as unknown as ArrayLike<ArrayLike<{ transcript: string }>>)
        .map((r) => r[0].transcript)
        .join(" ");
      onQueryChange(`${query}${query ? " " : ""}${transcript}`.trim());
    };
    recognition.onerror = () => setListening(false);
    recognition.onend = () => setListening(false);
    recognitionRef.current = recognition;
    setListening(true);
    recognition.start();
  }

  const cardRadius = variant === "hero" ? "rounded-[1.75rem]" : "rounded-[1.5rem]";
  const minHeight = variant === "hero" ? "min-h-20" : "min-h-14";
  const rows = variant === "hero" ? 2 : 2;

  return (
    <div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (pending) return;
          onSubmit(readyDocumentIds);
        }}
        className={variant === "sticky" ? "sticky bottom-5 mx-auto max-w-2xl" : "mt-8 w-full"}
      >
        <div className={`kriton-composer-surface ${cardRadius} border p-4 shadow-[0_18px_48px_rgba(18,34,32,0.08)]`}>
          {attachments.length > 0 && (
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
                    onClick={() => onAttachmentsChange((previous) => previous.filter((entry) => entry.id !== item.id))}
                    aria-label={`Remove ${item.name}`}
                    className="shrink-0 rounded p-0.5 text-muted hover:bg-soft"
                  >
                    <X size={13} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <textarea
            ref={textareaRef}
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={variant === "hero" ? "Ask Kriton..." : "Ask a follow-up..."}
            rows={rows}
            className={`${minHeight} w-full resize-none rounded-xl !border-transparent !bg-transparent px-1 py-1 text-base font-medium leading-7 text-ink !shadow-none outline-none placeholder:text-muted`}
          />

          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
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
                    <span className="hidden sm:inline">
                      {(() => {
                        const uploading = attachments.filter((item) => item.status === "uploading");
                        if (uploading.length > 0) {
                          const mean = uploading.reduce((total, item) => total + item.progress, 0) / uploading.length;
                          return uploading.length > 1
                            ? `Uploading ${uploading.length} files ${Math.round(mean * 100)}%`
                            : `Uploading ${Math.round(mean * 100)}%`;
                        }
                        return "Processing…";
                      })()}
                    </span>
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
                  onChange={(event) => {
                    const document = documents.find((item) => item.id === event.target.value);
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
                          }]
                    ));
                  }}
                  className="h-9 max-w-48 rounded-full !border-transparent !bg-soft px-3 text-xs font-semibold text-ink outline-none disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="">Saved documents</option>
                  {documents
                    .filter((document) => document.status === "READY")
                    .filter((document) => !attachments.some((entry) => entry.documentId === document.id))
                    .map((document) => (
                      <option key={document.id} value={document.id}>{document.filename}</option>
                    ))}
                </select>
              )}
            </div>

            <div className="flex min-w-0 items-center justify-end gap-2">
              <select
                value={jurisdiction}
                onChange={(e) => onJurisdictionChange(e.target.value)}
                className="hidden h-9 rounded-full !border-transparent !bg-soft px-3 text-xs font-semibold text-ink !shadow-none outline-none hover:bg-line/40 sm:block"
              >
                {JURISDICTIONS.map((j) => (
                  <option key={j} value={j}>{j || "Any"}</option>
                ))}
              </select>
              <button
                type="button"
                onClick={toggleVoice}
                aria-label={listening ? "Stop voice input" : "Voice input"}
                title={voiceError ?? undefined}
                className={`flex h-9 w-9 items-center justify-center rounded-full transition ${
                  listening ? "animate-pulse bg-bad/10 text-bad" : "text-muted hover:bg-soft"
                }`}
              >
                <Mic size={19} />
              </button>
              <button
                type="submit"
                disabled={submitting || !query.trim() || pending}
                className="flex h-9 w-9 items-center justify-center rounded-full bg-brand text-white transition hover:bg-brand-2 disabled:opacity-40"
                aria-label={variant === "hero" ? "Ask Kriton" : "Ask follow-up"}
              >
                {submitting ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={17} />}
              </button>
            </div>
          </div>
        </div>
      </form>

      {voiceError && <p className="mt-2 text-center text-xs text-muted">{voiceError}</p>}
      {error && (
        <div className="mt-3 rounded-xl border border-bad/30 bg-bad/5 px-4 py-2.5 text-sm text-bad" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
