// Pure helpers for the Promos page, kept separate from the component so
// they're testable without a browser/test runner (none is wired up in this
// project yet — see prds/promos-tracker/prd.md).

export function sortByExpiry(promos) {
  return [...promos].sort(
    (a, b) => new Date(a.expiry_date) - new Date(b.expiry_date)
  );
}

export function isExpiringSoon(promo, now = new Date()) {
  if (promo.status !== "available") return false;
  const msPerDay = 24 * 60 * 60 * 1000;
  const daysUntilExpiry = (new Date(promo.expiry_date) - now) / msPerDay;
  return daysUntilExpiry >= 0 && daysUntilExpiry <= 3;
}

// Display ordering for the Promos page: available promos first (soonest
// expiry first among them), used/expired pushed to the bottom.
export function sortForDisplay(promos) {
  const rank = (p) => (p.status === "available" ? 0 : 1);
  return [...promos].sort((a, b) => {
    const diff = rank(a) - rank(b);
    if (diff !== 0) return diff;
    return new Date(a.expiry_date) - new Date(b.expiry_date);
  });
}

const KNOWN_SPORTSBOOKS = [
  "DraftKings",
  "FanDuel",
  "BetMGM",
  "Caesars",
  "ESPN Bet",
  "Fanatics",
  "bet365",
];

// Order matters — more specific phrases are checked first.
const TYPE_KEYWORDS = [
  { type: "deposit_match", patterns: [/deposit match/i, /\bmatch\b/i] },
  { type: "odds_boost", patterns: [/odds boost/i, /\bboost\b/i] },
  { type: "free_bet", patterns: [/free bet/i] },
  {
    type: "signup_bonus",
    patterns: [
      /sign[\s-]?up/i,
      /welcome/i,
      /bonus bet/i,
      /bet\s*\$?\d+(\.\d+)?\s*get\s*\$?\d+/i,
    ],
  },
];

// Plain-text parser for the paste-to-fill box. No LLM, no network — just
// regex/string matching against a known sportsbook list and a few keyword
// rules. Any field it can't confidently determine is returned as "" so the
// caller can leave it (or the existing form value) alone.
export function parsePromoText(text, now = new Date()) {
  const result = { sportsbook: "", promo_type: "", amount: "", expiry_date: "" };
  if (!text || !text.trim()) return result;

  const sportsbook = KNOWN_SPORTSBOOKS.find((b) =>
    text.toLowerCase().includes(b.toLowerCase())
  );
  if (sportsbook) result.sportsbook = sportsbook;

  for (const { type, patterns } of TYPE_KEYWORDS) {
    if (patterns.some((p) => p.test(text))) {
      result.promo_type = type;
      break;
    }
  }

  const dateMatch = text.match(/(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?/);
  if (dateMatch) {
    const [, mStr, dStr, yStr] = dateMatch;
    const month = parseInt(mStr, 10);
    const day = parseInt(dStr, 10);
    let year;
    if (yStr) {
      year = yStr.length === 2 ? 2000 + parseInt(yStr, 10) : parseInt(yStr, 10);
    } else {
      year = now.getFullYear();
      const candidate = new Date(year, month - 1, day);
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      if (candidate < today) year += 1; // no year given — assume the next occurrence
    }
    const mm = String(month).padStart(2, "0");
    const dd = String(day).padStart(2, "0");
    result.expiry_date = `${year}-${mm}-${dd}`;
  }

  // Amount: whatever's left after stripping a leading "<sportsbook>:" and a
  // trailing "expires <date>" clause.
  let amountText = text;
  if (sportsbook) {
    const prefix = new RegExp(`^\\s*${sportsbook}\\s*:?\\s*`, "i");
    amountText = amountText.replace(prefix, "");
  }
  amountText = amountText.replace(
    /,?\s*expires?\s+\d{1,2}\/\d{1,2}(?:\/\d{2,4})?\.?\s*$/i,
    ""
  );
  amountText = amountText.trim().replace(/[.,]$/, "");
  result.amount = amountText;

  return result;
}
