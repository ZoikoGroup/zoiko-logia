import { ReactNode } from "react";

export function Card({
  title, action, className, children,
}: {
  title?: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={`rounded-lg border border-line bg-panel shadow-[0_10px_28px_rgba(11,95,122,0.08)] p-5 ${className ?? ""}`}>
      {(title || action) && (
        <div className="flex items-center justify-between mb-4">
          {title && <h2 className="text-base font-bold text-ink">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
