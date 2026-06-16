import { useEffect, useState } from "react";
import client from "../api/client";

export default function Props() {
  const [edges, setEdges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    client
      .get("/api/v1/props/edges")
      .then((r) => setEdges(r.data.edges ?? []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="p-8">
      <h1 className="text-3xl font-bold mb-6">Prop Edges</h1>
      {loading && <p className="text-slate-400 animate-pulse">Loading…</p>}
      {error && <p className="text-edge-negative">{error}</p>}
      {!loading && !error && edges.length === 0 && (
        <p className="text-slate-400">No +EV prop opportunities found right now.</p>
      )}
      <div className="space-y-3">
        {edges.map((edge) => (
          <div
            key={edge.event_id}
            className="bg-slate-800 rounded-2xl p-5 border border-slate-700 flex items-center justify-between"
          >
            <div>
              <p className="font-semibold">{edge.description}</p>
              <p className="text-slate-400 text-sm">
                Model: {(edge.model_probability * 100).toFixed(1)}% · Best source: {edge.best_source}
              </p>
            </div>
            <div className="text-right">
              <p
                className={`text-xl font-bold ${
                  edge.best_edge >= 0 ? "text-edge-positive" : "text-edge-negative"
                }`}
              >
                {edge.best_edge >= 0 ? "+" : ""}
                {(edge.best_edge * 100).toFixed(1)}%
              </p>
              <p className="text-slate-400 text-xs">edge</p>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
