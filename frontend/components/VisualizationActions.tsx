"use client";

import { useRef, useState } from "react";
import { AlertTriangle, Check, Download, FileSpreadsheet, ImageDown, Loader2, Save } from "lucide-react";

type ActionStatus = "idle" | "working" | "success" | "error";

/** lockRef is a synchronous guard checked before any state update — React
 * state changes are batched/async, so a rapid double-click can fire twice
 * before a `disabled` re-render lands. The ref catches that race; the
 * `disabled` attribute (driven by state) covers the rest of the in-flight
 * window and gives the button its visible pressed/disabled state. */
function useVisualizationAction(run: () => Promise<boolean> | boolean | void) {
  const [status, setStatus] = useState<ActionStatus>("idle");
  const lockRef = useRef(false);

  const trigger = async () => {
    if (lockRef.current) return;
    lockRef.current = true;
    setStatus("working");
    try {
      const result = await run();
      setStatus(result === false ? "error" : "success");
    } catch {
      setStatus("error");
    } finally {
      lockRef.current = false;
      setTimeout(() => setStatus((current) => (current === "working" ? current : "idle")), 2500);
    }
  };

  return { status, trigger };
}

function ActionButton({
  label, icon: Icon, status, onClick,
}: {
  label: string;
  icon: typeof Download;
  status: ActionStatus;
  onClick: () => void;
}) {
  const StatusIcon = status === "working" ? Loader2 : status === "success" ? Check : status === "error" ? AlertTriangle : Icon;
  const statusText = status === "working" ? "Working…" : status === "success" ? "Done" : status === "error" ? "Failed — try again" : label;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={status === "working"}
      aria-busy={status === "working"}
      className="flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-[11px] font-semibold text-muted transition hover:border-brand/40 hover:text-ink disabled:cursor-not-allowed disabled:opacity-60"
    >
      <StatusIcon
        size={13}
        aria-hidden="true"
        className={status === "working" ? "animate-spin" : status === "success" ? "text-ok" : status === "error" ? "text-bad" : ""}
      />
      <span aria-live="polite">{statusText}</span>
    </button>
  );
}

export type VisualizationActionsProps = {
  onDownloadPng?: () => boolean | Promise<boolean>;
  /** Puts the rendered figure on the clipboard as an image, for pasting
   * straight into a report or deck. Same rasterization as the PNG download. */
  onCopyImage?: () => boolean | Promise<boolean>;
  onExportCsv?: () => void | Promise<void>;
  onSave?: () => Promise<boolean>;
};

/** Only the actions applicable to the calling renderer are ever rendered —
 * AnswerVisualizations.tsx passes exactly one of these prop combinations
 * per visualization kind (ECharts: all three, Cytoscape: all three, Mermaid:
 * PNG + save only); a text-only answer never renders this component. */
export function VisualizationActions({ onDownloadPng, onCopyImage, onExportCsv, onSave }: VisualizationActionsProps) {
  const png = useVisualizationAction(async () => (onDownloadPng ? await onDownloadPng() : false));
  const copyImage = useVisualizationAction(async () => (onCopyImage ? await onCopyImage() : false));
  const csv = useVisualizationAction(async () => {
    await onExportCsv?.();
    return true;
  });
  const save = useVisualizationAction(async () => (onSave ? await onSave() : false));

  if (!onDownloadPng && !onCopyImage && !onExportCsv && !onSave) return null;

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Visualization actions">
      {onDownloadPng && <ActionButton label="Download PNG" icon={Download} status={png.status} onClick={png.trigger} />}
      {onCopyImage && <ActionButton label="Copy image" icon={ImageDown} status={copyImage.status} onClick={copyImage.trigger} />}
      {onExportCsv && <ActionButton label="Export CSV" icon={FileSpreadsheet} status={csv.status} onClick={csv.trigger} />}
      {onSave && <ActionButton label="Save" icon={Save} status={save.status} onClick={save.trigger} />}
    </div>
  );
}
