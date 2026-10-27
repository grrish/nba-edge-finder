import { useEffect, useState } from "react";
import client from "../api/client";
import { isExpiringSoon, parsePromoText, sortForDisplay } from "../utils/promos";

const PROMO_TYPES = [
  { value: "signup_bonus", label: "Signup bonus" },
  { value: "odds_boost", label: "Odds boost" },
  { value: "free_bet", label: "Free bet" },
  { value: "deposit_match", label: "Deposit match" },
  { value: "other", label: "Other" },
];

const EMPTY_FORM = {
  sportsbook: "",
  promo_type: "signup_bonus",
  amount: "",
  expiry_date: "",
  notes: "",
};

export default function Promos() {
  const [promos, setPromos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [pasteText, setPasteText] = useState("");

  function loadPromos() {
    setLoading(true);
    return client
      .get("/api/v1/promos")
      .then((r) => setPromos(r.data.promos ?? []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadPromos();
  }, []);

  function handleChange(e) {
    setForm({ ...form, [e.target.name]: e.target.value });
  }

  function handlePasteTextChange(e) {
    const value = e.target.value;
    setPasteText(value);
    const parsed = parsePromoText(value);
    setForm((prev) => ({
      ...prev,
      sportsbook: parsed.sportsbook || prev.sportsbook,
      promo_type: parsed.promo_type || prev.promo_type,
      amount: parsed.amount || prev.amount,
      expiry_date: parsed.expiry_date || prev.expiry_date,
    }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await client.post("/api/v1/promos", form);
      setForm(EMPTY_FORM);
      setPasteText("");
      await loadPromos();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function setStatus(id, status) {
    try {
      await client.patch(`/api/v1/promos/${id}`, { status });
      await loadPromos();
    } catch (err) {
      setError(err.message);
    }
  }

  async function removePromo(id) {
    try {
      await client.delete(`/api/v1/promos/${id}`);
      await loadPromos();
    } catch (err) {
      setError(err.message);
    }
  }

  const sorted = sortForDisplay(promos);

  return (
    <main className="p-8">
      <h1 className="text-3xl font-bold mb-6">Promos</h1>

      <textarea
        value={pasteText}
        onChange={handlePasteTextChange}
        placeholder={'Paste a promo here to fill the form below, e.g. "DraftKings: bet $5 get $150 in bonus bets, expires 10/31"'}
        rows={2}
        className="w-full bg-slate-800 border border-slate-700 rounded-2xl px-4 py-3 text-sm mb-4 placeholder:text-slate-500"
      />

      <form
        onSubmit={handleSubmit}
        className="bg-slate-800 rounded-2xl p-5 border border-slate-700 mb-8 grid grid-cols-1 sm:grid-cols-2 gap-4"
      >
        <input
          name="sportsbook"
          value={form.sportsbook}
          onChange={handleChange}
          placeholder="Sportsbook (e.g. DraftKings)"
          required
          className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm"
        />
        <select
          name="promo_type"
          value={form.promo_type}
          onChange={handleChange}
          className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm"
        >
          {PROMO_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <input
          name="amount"
          value={form.amount}
          onChange={handleChange}
          placeholder="Amount (e.g. $50 free bet)"
          required
          className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm"
        />
        <input
          type="date"
          name="expiry_date"
          value={form.expiry_date}
          onChange={handleChange}
          required
          className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm"
        />
        <input
          name="notes"
          value={form.notes}
          onChange={handleChange}
          placeholder="Notes (optional)"
          className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm sm:col-span-2"
        />
        <button
          type="submit"
          disabled={submitting}
          className="bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-semibold sm:col-span-2"
        >
          {submitting ? "Adding…" : "Add promo"}
        </button>
      </form>

      {loading && <p className="text-slate-400 animate-pulse">Loading…</p>}
      {error && <p className="text-edge-negative mb-4">{error}</p>}
      {!loading && !error && sorted.length === 0 && (
        <p className="text-slate-400">No promos logged yet.</p>
      )}

      <div className="space-y-3">
        {sorted.map((promo) => {
          const flagged = isExpiringSoon(promo);
          const dimmed = promo.status !== "available";
          return (
            <div
              key={promo.id}
              className={`bg-slate-800 rounded-2xl p-5 border flex items-center justify-between ${
                flagged ? "border-amber-500" : "border-slate-700"
              } ${dimmed ? "opacity-50" : ""}`}
            >
              <div>
                <p className="font-semibold">
                  {promo.sportsbook} —{" "}
                  {PROMO_TYPES.find((t) => t.value === promo.promo_type)?.label ??
                    promo.promo_type}
                </p>
                <p className="text-slate-400 text-sm">
                  {promo.amount} · expires {promo.expiry_date} · {promo.status}
                  {promo.notes ? ` · ${promo.notes}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-3">
                {flagged && (
                  <span className="text-xs font-bold text-amber-400 bg-amber-500/10 px-2 py-1 rounded-lg">
                    Expiring soon
                  </span>
                )}
                {promo.status === "available" && (
                  <button
                    onClick={() => setStatus(promo.id, "used")}
                    className="text-xs text-slate-300 hover:text-white border border-slate-600 rounded-lg px-3 py-1.5"
                  >
                    Mark used
                  </button>
                )}
                {promo.status === "used" && (
                  <button
                    onClick={() => setStatus(promo.id, "available")}
                    className="text-xs text-slate-300 hover:text-white border border-slate-600 rounded-lg px-3 py-1.5"
                  >
                    Mark available
                  </button>
                )}
                <button
                  onClick={() => removePromo(promo.id)}
                  className="text-xs text-edge-negative hover:text-red-400 border border-slate-600 rounded-lg px-3 py-1.5"
                >
                  Delete
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </main>
  );
}
