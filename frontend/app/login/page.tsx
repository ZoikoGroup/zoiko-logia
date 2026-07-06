"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { BrandMark } from "@/components/layout/AppHeader";
import { login, ApiError } from "@/lib/api";

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
    <div className="min-h-screen w-full flex items-center justify-center bg-bg p-6">
      <div className="w-full max-w-sm rounded-2xl border border-line bg-panel shadow-[0_10px_28px_rgba(11,95,122,0.08)] p-8">
        <div className="flex flex-col items-center text-center mb-6">
          <BrandMark className="h-16 w-16" />
          <h1 className="mt-4 text-lg font-extrabold text-ink tracking-tight">ZoikoLogia Governance</h1>
          <p className="mt-1 text-xs text-muted">Sign in to access the governance dashboard</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-muted mb-1.5">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@zoiko.com"
              className="w-full rounded-lg border border-line bg-soft px-3 py-2.5 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted mb-1.5">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full rounded-lg border border-line bg-soft px-3 py-2.5 text-sm text-ink placeholder:text-muted outline-none focus:border-brand"
            />
          </div>

          {error && <p className="text-xs text-bad">{error}</p>}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-brand text-white text-sm font-semibold py-2.5 hover:bg-brand-2 disabled:opacity-60"
          >
            {submitting ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
