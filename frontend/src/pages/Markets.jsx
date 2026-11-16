import { useEffect, useState } from "react";
import client from "../api/client";

export default function Markets() {
  const [markets, setMarkets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    client
      .get("/api/v1/games/markets", { params: { tag_slug: "wnba" } })
      .then((r) => setMarkets(r.data ?? []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="p-8">
      <h1 className="text-3xl font-bold mb-6">Polymarket Markets</h1>
      {loading && <p className="text-slate-400 animate-pulse">Loading…</p>}
      {error && <p className="text-edge-negative">{error}</p>}
      {!loading && !error && markets.length === 0 && (
        <p className="text-slate-400">No live markets found right now.</p>
      )}
      <div className="space-y-3">
        {markets.map((m) => (
          <div
            key={m.market_id}
            className="bg-slate-800 rounded-2xl p-5 border border-slate-700 flex items-center justify-between"
          >
            <p className="font-semibold">{m.question}</p>
            <div className="text-right">
              <p className="text-xl font-bold text-brand-500">
                {(m.price_a * 100).toFixed(0)}%
              </p>
              <p className="text-slate-400 text-xs">{m.outcome_a}</p>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
