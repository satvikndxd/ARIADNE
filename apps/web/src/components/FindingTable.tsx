import { useNavigate } from "react-router-dom";

import type { FindingOut } from "../types/api";
import { ConfidenceBadge, SeverityBadge, StatusBadge } from "./badges";

export function FindingTable({ findings }: { findings: FindingOut[] }) {
  const nav = useNavigate();
  return (
    <div className="overflow-auto scroll-thin h-full">
      <table className="dense">
        <thead>
          <tr>
            <th>id</th><th>title</th><th>severity</th><th>component</th><th>status</th>
            <th>confidence</th><th>evidence</th><th>source</th><th>created</th>
          </tr>
        </thead>
        <tbody>
          {findings.map((f) => (
            <tr key={f.id} className="cursor-pointer" onClick={() => nav(`/findings?f=${f.id}`)}>
              <td className="font-mono text-[10.5px] text-slate-500">{f.id.slice(0, 12)}</td>
              <td className="text-slate-200 max-w-[380px]">{f.title}</td>
              <td><SeverityBadge severity={f.severity} /></td>
              <td className="font-mono text-[11px]">{f.component_name || "—"}</td>
              <td><StatusBadge status={f.status} /></td>
              <td><ConfidenceBadge value={f.confidence} /></td>
              <td className="font-mono text-[11px] text-slate-400">{f.evidence.length}</td>
              <td className="font-mono text-[10.5px] text-slate-500">{f.source}</td>
              <td className="font-mono text-[10.5px] text-slate-500">{f.created_at?.slice(0, 10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
