"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, BookOpenCheck, BrainCircuit, LockKeyhole, ShieldCheck } from "lucide-react";
import { login, ApiError } from "@/lib/api";
import { BrandMark } from "@/components/layout/AppHeader";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const { access_token } = await login(email, password);
      document.cookie = `zoiko_auth=${access_token}; path=/; max-age=${60 * 60 * 24 * 7}`;
      router.push("/");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Incorrect email or password.");
      } else {
        setError("Could not reach the server. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen w-full bg-bg text-ink">
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[minmax(0,1fr)_460px]">
        <section className="relative hidden overflow-hidden border-r border-line bg-panel lg:block">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_24%_20%,rgba(22,121,154,0.18),transparent_34%),radial-gradient(circle_at_76%_72%,rgba(243,196,55,0.16),transparent_28%)]" />
          <div className="relative flex h-full flex-col justify-between p-10">
            <div className="flex items-center gap-3">
              <BrandMark className="h-12 w-12" />
              <div>
                <p className="text-sm font-bold text-ink">ZoikoLogia</p>
                <p className="text-xs text-muted">Governance intelligence workspace</p>
              </div>
            </div>

            <div className="max-w-2xl">
              <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-semibold text-brand">
                <BrainCircuit size={14} />
                Ask Kriton after sign in
              </div>
              <h1 className="text-5xl font-bold leading-tight tracking-normal text-ink">
                Source-governed AI for accounting decisions.
              </h1>
              <p className="mt-5 max-w-xl text-sm leading-7 text-muted">
                Review standards, attach documents, route risk, and keep every Kriton answer tied to audit evidence.
              </p>
            </div>

            <div className="grid max-w-2xl grid-cols-3 gap-3">
              {[
                { icon: BookOpenCheck, label: "Source checks" },
                { icon: ShieldCheck, label: "Safety routing" },
                { icon: LockKeyhole, label: "Audit trail" },
              ].map(({ icon: Icon, label }) => (
                <div key={label} className="rounded-lg border border-line bg-bg/70 p-4 shadow-[0_10px_30px_rgba(11,95,122,0.06)]">
                  <Icon size={18} className="text-brand" />
                  <p className="mt-3 text-xs font-bold text-ink">{label}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="flex min-h-screen items-center justify-center px-5 py-8">
          <div className="w-full max-w-md">
            <div className="mb-8 text-center lg:hidden">
              <BrandMark className="mx-auto h-16 w-16" />
              <h1 className="mt-4 text-2xl font-bold text-ink">ZoikoLogia</h1>
              <p className="mt-1 text-sm text-muted">Sign in to open Ask Kriton.</p>
            </div>

            <div className="rounded-2xl border border-line bg-panel p-6 shadow-[0_18px_50px_rgba(11,95,122,0.10)] sm:p-8">
              <div className="mb-7">
                <div className="mb-4 hidden lg:block">
                  <BrandMark className="h-14 w-14" />
                </div>
                <p className="text-xs font-bold uppercase text-brand">Welcome back</p>
                <h2 className="mt-2 text-2xl font-bold tracking-normal text-ink">Sign in to ZoikoLogia</h2>
                <p className="mt-2 text-sm leading-6 text-muted">
                  Continue to the redesigned Ask Kriton assistant workspace.
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="mb-1.5 block text-xs font-semibold text-muted">Email</label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@zoiko.com"
                    autoComplete="email"
                    className="h-11 w-full rounded-lg border border-line bg-soft px-3 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-semibold text-muted">Password</label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Enter your password"
                    autoComplete="current-password"
                    className="h-11 w-full rounded-lg border border-line bg-soft px-3 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
                  />
                </div>

                {error && (
                  <p className="rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-xs font-medium text-bad">
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={submitting}
                  className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-ink px-4 text-sm font-bold text-panel shadow-[0_12px_28px_rgba(21,25,34,0.18)] transition-colors hover:bg-brand disabled:opacity-60"
                >
                  {submitting ? "Signing in..." : "Sign in and open Ask Kriton"}
                  {!submitting && <ArrowRight size={16} />}
                </button>
              </form>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
