import { useEffect, useState } from "react";
import client from "../api/client";

export default function Dashboard() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    client
      .get("/health")
      .then((r) => setHealth(r.data))
      .catch((e) => setError(e.message));
  }, []);

  return (
    <main className="p-8">
      <h1 className="text-3xl font-bold mb-6">Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700">
          <p className="text-slate-400 text-sm uppercase tracking-wide mb-1">API Status</p>
          {error ? (
            <p className="text-edge-negative font-semibold">{error}</p>
          ) : health ? (
            <p className="text-edge-positive font-semibold capitalize">{health.status}</p>
          ) : (
            <p className="text-slate-500 animate-pulse">Checking…</p>
          )}
        </div>
        <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700">
          <p className="text-slate-400 text-sm uppercase tracking-wide mb-1">Environment</p>
          <p className="font-semibold capitalize">{health?.environment ?? "—"}</p>
        </div>
        <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700">
          <p className="text-slate-400 text-sm uppercase tracking-wide mb-1">Edges Found</p>
          <p className="text-3xl font-bold text-brand-500">—</p>
        </div>
      </div>
    </main>
  );
}
