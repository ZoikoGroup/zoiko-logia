export default function Loading() {
  return (
    <main className="flex-1 p-4 lg:p-6" role="status" aria-label="Loading page" aria-busy="true">
      <span className="sr-only">Opening your workspace page…</span>
      <div aria-hidden="true" className="w-full min-w-0 space-y-4 motion-safe:animate-pulse">
        <div className="h-5 w-48 rounded bg-soft" />
        <div className="h-9 w-64 rounded bg-soft" />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map(i => <div key={i} className="h-28 rounded-xl border border-line bg-panel" />)}
        </div>
        <div className="h-72 rounded-xl border border-line bg-panel" />
      </div>
    </main>
  );
}
