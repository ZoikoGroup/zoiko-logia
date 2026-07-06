import { Card } from "./Card";
import { Pill } from "./Pill";

export function License() {
  return (
    <Card title="License-expiry countdown" action={<Pill tone="warn">Beyond competitor baseline</Pill>}>
      <div className="grid grid-cols-[80px_1fr] gap-3 items-center">
        <div className="h-20 rounded-xl border border-line bg-warn/10 text-warn flex items-center justify-center text-3xl font-extrabold">
          18
        </div>
        <div>
          <div className="font-semibold text-ink">IFRS Foundation Standards API</div>
          <p className="mt-1 text-xs text-muted leading-relaxed">
            Expires in 18 days. Display allowed; export blocked after expiry unless renewal evidence is attached.
          </p>
          <button className="mt-2.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-medium text-ink hover:bg-soft">
            Open renewal task
          </button>
        </div>
      </div>
    </Card>
  );
}
