"use client";

import { useEffect, useState } from "react";

type Connection = "Checking" | "Connected" | "Disconnected" | "Unknown";
const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function Home() {
  const [backend, setBackend] = useState<Connection>("Checking");
  const [database, setDatabase] = useState<Connection>("Checking");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = setTimeout(() => controller.abort(), 10000);
    setBackend("Checking");
    setDatabase("Checking");

    async function checkHealth() {
      try {
        const response = await fetch(`${apiBaseUrl.replace(/\/$/, "")}/api/v1/health`, {
          signal: controller.signal, cache: "no-store",
        });
        const data: unknown = await response.json();
        if (!active) return;
        if (typeof data !== "object" || data === null || !("status" in data) || !("database" in data)) {
          throw new Error("Unexpected health response");
        }
        if (response.status === 200 && data.status === "ok" && data.database === "connected") {
          setBackend("Connected");
          setDatabase("Connected");
        } else if (response.status === 503 && data.status === "error" && data.database === "disconnected") {
          setBackend("Connected");
          setDatabase("Disconnected");
        } else {
          throw new Error("Unexpected health response");
        }
      } catch {
        if (active) { setBackend("Disconnected"); setDatabase("Unknown"); }
      } finally {
        clearTimeout(timeout);
      }
    }

    void checkHealth();
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [attempt]);

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <p className="text-sm font-semibold text-slate-500">Phase 1 · Development Environment</p>
      <h1 className="mt-3 text-3xl font-bold tracking-tight">SNS Trend &amp; Performance Analyzer</h1>
      <p className="mt-4 text-slate-600">開発基盤の起動・接続状態を確認するページです。</p>
      <a href="/dashboard" className="mt-6 inline-block font-semibold text-teal-800 underline">Overviewを開く</a>
      <a href="/dashboard/settings" className="mt-6 inline-block font-semibold text-teal-800 underline">Settings / Importを開く</a>
      <a href="/dashboard/my-account" className="ml-5 mt-6 inline-block font-semibold text-teal-800 underline">My Accountを開く</a>
      <a href="/dashboard/trends" className="ml-5 mt-6 inline-block font-semibold text-teal-800 underline">Trend Explorerを開く</a>
      <a href="/dashboard/competitors" className="ml-5 mt-6 inline-block font-semibold text-teal-800 underline">Competitorを開く</a>
      <a href="/dashboard/gap" className="ml-5 mt-6 inline-block font-semibold text-teal-800 underline">Gap Analysisを開く</a>
      <dl aria-live="polite" className="mt-8 space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        {[["Frontend", "Running"], ["Backend API", backend], ["Database", database]].map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-4">
            <dt className="font-medium">{label}</dt>
            <dd className={value === "Connected" || value === "Running" ? "text-emerald-700" : "text-slate-600"}>{value}</dd>
          </div>
        ))}
      </dl>
      <button type="button" onClick={() => setAttempt((value) => value + 1)} className="mt-6 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2">
        接続を再確認
      </button>
      <p className="mt-4 text-sm text-slate-500">Database が Unknown の場合は、Backend に到達できず接続状態を確認できません。</p>
    </main>
  );
}
