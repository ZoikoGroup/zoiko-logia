"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
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
import { getAuthToken, uploadKritonAttachment, ApiError } from "@/lib/api";

const JURISDICTIONS = ["", "UK", "US", "US-CA", "IFRS", "UAE", "India", "EU"];
const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".xlsx", ".pptx"];

type Attachment = { name: string; status: "uploading" | "success" | "error"; progress: number; chunkCount?: number; error?: string };

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
  submitting,
  error,
}: {
  variant: "hero" | "sticky";
  query: string;
  onQueryChange: (value: string) => void;
  jurisdiction: string;
  onJurisdictionChange: (value: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  error: string | null;
}) {
  const [attachment, setAttachment] = useState<Attachment | null>(null);
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

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  }

  async function handleFileSelected(file: File) {
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      setAttachment({ name: file.name, status: "error", progress: 0, error: `Unsupported file type — allowed: ${ACCEPTED_EXTENSIONS.join(", ")}` });
      return;
    }
    const token = getAuthToken();
    if (!token) {
      setAttachment({ name: file.name, status: "error", progress: 0, error: "Please sign in before uploading." });
      return;
    }
    setAttachment({ name: file.name, status: "uploading", progress: 0 });
    try {
      const result = await uploadKritonAttachment(token, file, (fraction) => {
        setAttachment((prev) => (prev && prev.name === file.name ? { ...prev, progress: fraction } : prev));
      });
      setAttachment({ name: file.name, status: "success", progress: 1, chunkCount: result.chunk_count });
    } catch (err) {
      setAttachment({ name: file.name, status: "error", progress: 0, error: err instanceof ApiError ? err.message : "Upload failed." });
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

  return (
    <div>
      <form
        onSubmit={(e) => { e.preventDefault(); onSubmit(); }}
        className={variant === "sticky" ? "sticky bottom-5 mx-auto max-w-2xl" : "mt-8 w-full"}
      >
        <div className={`kriton-composer-surface ${cardRadius} border p-4 shadow-[0_18px_48px_rgba(18,34,32,0.08)]`}>
          {attachment && (
            <div className="mb-3 flex items-center gap-2 rounded-xl border border-line bg-soft/60 px-3 py-2 text-xs">
              {attachment.status === "uploading" && <Loader2 size={14} className="shrink-0 animate-spin text-brand" />}
              {attachment.status === "success" && <CheckCircle2 size={14} className="shrink-0 text-ok" />}
              {attachment.status === "error" && <AlertTriangle size={14} className="shrink-0 text-bad" />}
              <FileText size={14} className="shrink-0 text-muted" />
              <span className="min-w-0 flex-1 truncate font-medium text-ink">{attachment.name}</span>
              <span className="shrink-0 text-muted">
                {attachment.status === "uploading" && `${Math.round(attachment.progress * 100)}%`}
                {attachment.status === "success" && `${attachment.chunkCount} chunks`}
                {attachment.status === "error" && attachment.error}
              </span>
              <button type="button" onClick={() => setAttachment(null)} aria-label="Remove attachment" className="shrink-0 rounded p-0.5 text-muted hover:bg-soft">
                <X size={13} />
              </button>
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
            <div>
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_EXTENSIONS.join(",")}
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFileSelected(file);
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={attachment?.status === "uploading"}
                aria-label="Attach a document"
                className="flex h-9 w-9 items-center justify-center rounded-full text-muted transition hover:bg-soft disabled:opacity-50"
              >
                {attachment?.status === "uploading" ? <Loader2 size={17} className="animate-spin" /> : <Plus size={19} />}
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
                disabled={submitting || !query.trim()}
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
