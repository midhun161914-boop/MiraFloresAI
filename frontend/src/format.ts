const money0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const money2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function fmtMoney(v: number): string {
  return Number.isInteger(v) ? money0.format(v) : money2.format(v);
}

/** Accounting style: negatives in parentheses, e.g. (8,256). */
export function fmtAccounting(v: number): string {
  return v < 0 ? `(${fmtMoney(-v)})` : fmtMoney(v);
}

/** "Balance due 4,220" / "Refund 8,256" — a negative balance due is an overpayment. */
export function fmtBalance(v: number): string {
  return v < 0 ? `Refund ${fmtMoney(-v)}` : `Balance due ${fmtMoney(v)}`;
}

export function fmtValue(v: unknown, type?: string): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") {
    if (type === "percent") return `${v}%`;
    // Accounting style everywhere a CPA reads amounts: (238), not -238.
    const s = type === "money" ? money2.format(Math.abs(v)) : fmtMoney(Math.abs(v));
    return v < 0 ? `(${s})` : s;
  }
  return String(v);
}

export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })
    : d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

/** "taxpayer" -> "Ngozi Okafor (taxpayer)", using the household from /api/overview. */
export function belongsLabel(b: string, people: { id: string; name: string; role: string }[] = []): string {
  if (b === "joint") return "Joint";
  const [role, id] = b.split(":");
  const person = id ? people.find((p) => p.id === id) : people.find((p) => p.role === role);
  return person ? `${person.name.split(" ")[0]} (${role})` : b;
}
