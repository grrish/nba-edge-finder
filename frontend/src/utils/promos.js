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
