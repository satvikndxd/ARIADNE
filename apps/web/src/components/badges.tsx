import type { Severity } from "../types/api";

const SEV: Record<Severity, string> = {
  high: "border-cad-red/70 text-cad-red",
  medium: "border-cad-blue/70 text-cad-blue",
  low: "border-line text-slate-400",
  info: "border-line text-slate-500",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`chip ${SEV[severity] ?? SEV.info}`}>{severity}</span>;
}

export function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const tone = pct >= 80 ? "text-cad-green border-cad-green/50" : pct >= 55 ? "text-cad-amber border-cad-amber/50" : "text-slate-400 border-line";
  return <span className={`chip ${tone}`} title="confidence">{pct}%</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    open: "border-cad-orange/70 text-cad-orange",
    needs_review: "border-cad-amber/70 text-cad-amber",
    accepted: "border-cad-green/70 text-cad-green",
    rejected: "border-line text-slate-500",
    resolved: "border-cad-blue/70 text-cad-blue",
    completed: "border-cad-green/70 text-cad-green",
    running: "border-cad-blue/70 text-cad-blue",
    queued: "border-line text-slate-400",
    failed: "border-cad-red/70 text-cad-red",
  };
  return <span className={`chip ${map[status] ?? "border-line text-slate-400"}`}>{status.replace("_", " ")}</span>;
}

export function SeverityColor(sev: Severity): string {
  return sev === "high" ? "#d64533" : sev === "medium" ? "#4d8fd1" : "#6b7480";
}
