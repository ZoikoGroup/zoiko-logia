"use client";

import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type KeyboardEvent,
  type SetStateAction,
} from "react";
import {
  AlertTriangle,
  ArrowUp,
  CheckCircle2,
  FileText,
  Loader2,
  Mic,
  Plus,
  X,
} from "lucide-react";
import {
  getAuthToken,
  uploadKritonAttachment,
  deleteKritonAttachment,
  ApiError,
  type AttachmentUploadResult,
} from "@/lib/api";

const JURISDICTIONS = ["", "UK", "US", "US-CA", "IFRS", "UAE", "India", "EU"];
const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".txt", ".md"];

/** Matches the backend's per-file cap (_MAX_ATTACHMENT_BYTES). Checked here as
 *  well so a 60MB file is rejected instantly instead of after a long upload
 *  that ends in a 413. */
const MAX_FILE_BYTES = 20 * 1024 * 1024;

/** How many files may back a single question. The limit is about the answer,
 *  not the upload: eight retrieved chunks spread across more than five
 *  documents gives each one too little room to be useful. */
const MAX_FILES = 5;

/** Owned by the PAGE, not by this component — see the note on the
 *  `attachments` prop for why that matters. */
export type Attachment = {
  /** Stable key for React — the filename is not unique enough (two uploads of
   *  the same name) and document_id does not exist until the upload returns. */
  key: string;
  name: string;
  status: "uploading" | "success" | "error";
  progress: number;
  documentId?: string;
  chunkCount?: number;
  error?: string;
};

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

function formatSize(bytes: number) {
  return bytes >= 1024 * 1024
    ? `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function Composer({
  variant,
  query,
  onQueryChange,
  jurisdiction,
  onJurisdictionChange,
  onSubmit,
  submitting,
  error,
  attachments,
  onAttachmentsChange,
}: {
  variant: "hero" | "sticky";
  query: string;
  onQueryChange: (value: string) => void;
  jurisdiction: string;
  onJurisdictionChange: (value: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  error: string | null;
  /** Attachment list, owned by the page.
   *
   *  This deliberately does NOT live in local state. The page renders a "hero"
   *  Composer before a conversation exists and a "sticky" one afterwards, so
   *  asking the first question unmounts one instance and mounts the other. With
   *  the list held locally, the file the user had just attached vanished at
   *  exactly that moment — the chip disappeared and the ids never reached the
   *  request, so the answer came back grounded only in web sources. Holding it
   *  one level up makes the attachment outlive the swap, which is also what
   *  lets the user ask several follow-up questions about the same document. */
  attachments: Attachment[];
  onAttachmentsChange: Dispatch<SetStateAction<Attachment[]>>;
}) {
  const setAttachments = onAttachmentsChange;
  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 220)}px`;
  }, [query]);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  }

  function patchAttachment(key: string, patch: Partial<Attachment>) {
    setAttachments((prev) => prev.map((a) => (a.key === key ? { ...a, ...patch } : a)));
  }

  /**
   * Uploads the chosen files ONE AT A TIME, deliberately.
   *
   * Five 20MB files sent together would be a 100MB request body — past most
   * reverse-proxy limits, and the server would have to hold the whole payload
   * in memory while extracting text from all five, which takes long enough to
   * exceed the request timeout. Sequential single-file requests give the user
   * the same "attach five files" experience while each request stays small and
   * fast, and one bad file fails on its own without taking the others with it.
   */
  async function handleFilesSelected(files: File[]) {
    setUploadNotice(null);

    const room = MAX_FILES - attachments.length;
    if (room <= 0) {
      setUploadNotice(`You can attach up to ${MAX_FILES} files to a question.`);
      return;
    }
    if (files.length > room) {
      setUploadNotice(
        `Only the first ${room} of ${files.length} files were added — the limit is ${MAX_FILES} per question.`,
      );
      files = files.slice(0, room);
    }

    const token = getAuthToken();
    if (!token) {
      setUploadNotice("Please sign in before uploading.");
      return;
    }

    for (const file of files) {
      const key = `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const ext = file.name.includes(".")
        ? file.name.slice(file.name.lastIndexOf(".")).toLowerCase()
        : "";

      if (!ACCEPTED_EXTENSIONS.includes(ext)) {
        setAttachments((prev) => [
          ...prev,
          { key, name: file.name, status: "error", progress: 0, error: `Unsupported type — allowed: ${ACCEPTED_EXTENSIONS.join(", ")}` },
        ]);
        continue;
      }
      if (file.size === 0) {
        setAttachments((prev) => [
          ...prev,
          { key, name: file.name, status: "error", progress: 0, error: "This file is empty" },
        ]);
        continue;
      }
      if (file.size > MAX_FILE_BYTES) {
        setAttachments((prev) => [
          ...prev,
          { key, name: file.name, status: "error", progress: 0, error: `${formatSize(file.size)} — over the 20 MB limit` },
        ]);
        continue;
      }

      setAttachments((prev) => [...prev, { key, name: file.name, status: "uploading", progress: 0 }]);
      try {
        const result: AttachmentUploadResult = await uploadKritonAttachment(token, file, (fraction) => {
          // Upload progress only reaches 100% when the bytes have arrived;
          // extraction happens after that, so the bar is capped at 95% until
          // the response lands. Showing 100% while the server is still parsing
          // would read as "done" for several more seconds.
          patchAttachment(key, { progress: Math.min(fraction, 0.95) });
        });
        if (result.status === "ready") {
          patchAttachment(key, {
            status: "success",
            progress: 1,
            documentId: result.document_id,
            chunkCount: result.chunk_count,
          });
        } else {
          // The upload succeeded but the file yielded no usable text. This is
          // shown as an error because that is what it means for the user: the
          // document will not contribute to any answer.
          patchAttachment(key, {
            status: "error",
            progress: 0,
            error: result.failure_reason ?? "No readable text found in this file",
          });
        }
      } catch (err) {
        patchAttachment(key, {
          status: "error",
          progress: 0,
          error: err instanceof ApiError ? err.message : "Upload failed",
        });
      }
    }
  }

  async function removeAttachment(attachment: Attachment) {
    setAttachments((prev) => prev.filter((a) => a.key !== attachment.key));
    setUploadNotice(null);
    // Also drop the indexed copy — leaving chunks behind for a document the
    // user has visibly removed would keep influencing answers.
    const token = getAuthToken();
    if (token && attachment.documentId) {
      try {
        await deleteKritonAttachment(token, attachment.documentId);
      } catch {
        /* The row is orphaned but unreachable from the UI; not worth alarming
           the user, who has already seen the attachment disappear. */
      }
    }
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
  const uploading = attachments.some((a) => a.status === "uploading");
  const atLimit = attachments.length >= MAX_FILES;

  return (
    <div>
      <form
        onSubmit={(e) => { e.preventDefault(); onSubmit(); }}
        className={variant === "sticky" ? "sticky bottom-5 mx-auto max-w-2xl" : "mt-8 w-full"}
      >
        <div className={`kriton-composer-surface ${cardRadius} border p-4 shadow-[0_18px_48px_rgba(18,34,32,0.08)]`}>
          {attachments.length > 0 && (
            <div className="mb-3 space-y-1.5">
              {attachments.map((attachment) => (
                <div
                  key={attachment.key}
                  className="flex items-center gap-2 rounded-xl border border-line bg-soft/60 px-3 py-2 text-xs"
                >
                  {attachment.status === "uploading" && <Loader2 size={14} className="shrink-0 animate-spin text-brand" />}
                  {attachment.status === "success" && <CheckCircle2 size={14} className="shrink-0 text-ok" />}
                  {attachment.status === "error" && <AlertTriangle size={14} className="shrink-0 text-bad" />}
                  <FileText size={14} className="shrink-0 text-muted" />
                  <span className="min-w-0 flex-1 truncate font-medium text-ink">{attachment.name}</span>
                  <span
                    className={`shrink-0 ${attachment.status === "error" ? "max-w-[16rem] truncate text-bad" : "text-muted"}`}
                    title={attachment.status === "error" ? attachment.error : undefined}
                  >
                    {attachment.status === "uploading" && `${Math.round(attachment.progress * 100)}%`}
                    {attachment.status === "success" &&
                      `${attachment.chunkCount} section${attachment.chunkCount === 1 ? "" : "s"} indexed`}
                    {attachment.status === "error" && attachment.error}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeAttachment(attachment)}
                    aria-label={`Remove ${attachment.name}`}
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
            data-kriton-composer=""
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={variant === "hero" ? "Ask Kriton..." : "Ask a follow-up..."}
            rows={rows}
            className={`${minHeight} w-full resize-none rounded-xl !border-transparent !bg-transparent px-1 py-1 text-base font-medium leading-7 text-ink !shadow-none outline-none placeholder:text-muted`}
          />

          <div className="flex items-center justify-between gap-3">
            <div>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={ACCEPTED_EXTENSIONS.join(",")}
                className="hidden"
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? []);
                  if (files.length) handleFilesSelected(files);
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading || atLimit}
                aria-label="Attach documents"
                title={atLimit ? `Up to ${MAX_FILES} files per question` : "Attach documents (PDF, Word, Excel, PowerPoint, CSV, text)"}
                className="flex h-9 w-9 items-center justify-center rounded-full text-muted transition hover:bg-soft disabled:opacity-50"
              >
                {uploading ? <Loader2 size={17} className="animate-spin" /> : <Plus size={19} />}
              </button>
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
                disabled={submitting || uploading || !query.trim()}
                className="flex h-9 w-9 items-center justify-center rounded-full bg-brand text-white transition hover:bg-brand-2 disabled:opacity-40"
                aria-label={variant === "hero" ? "Ask Kriton" : "Ask follow-up"}
              >
                {submitting ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={17} />}
              </button>
            </div>
          </div>
        </div>
      </form>

      {uploadNotice && <p className="mt-2 text-center text-xs text-muted">{uploadNotice}</p>}
      {voiceError && <p className="mt-2 text-center text-xs text-muted">{voiceError}</p>}
      {error && (
        <div className="mt-3 rounded-xl border border-bad/30 bg-bad/5 px-4 py-2.5 text-sm text-bad" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
