import type { SystemStatus } from "../types/api";
import { DEMO_USERS, type Role } from "../lib/api";

export function TopBar({ status, role, user, onUserChange }: {
  status?: SystemStatus; role: Role; user: string; onUserChange: (id: string) => void;
}) {
  return (
    <header className="h-11 shrink-0 border-b border-line bg-ink-900 flex items-center gap-4 px-4">
      <div className="font-mono text-[11px] text-slate-500">
        ORION EV <span className="text-slate-700">/</span> MOTOR MOUNT ASSEMBLY A-01
      </div>
      <div className="flex-1" />
      {status && (
        <div className="flex items-center gap-2 font-mono text-[10.5px]">
          <span className={`chip ${status.demo_mode ? "border-cad-amber/60 text-cad-amber" : "border-cad-green/60 text-cad-green"}`}>
            {status.demo_mode ? "demo analysis" : "live providers"}
          </span>
          <span className="chip border-line text-slate-500">llm:{status.llm.provider}</span>
          <span className="chip border-line text-slate-500">emb:{status.embeddings.provider}</span>
          <span className="chip border-line text-slate-500">vec:{status.vector_store}</span>
          <span className={`chip ${status.mcp.healthy ? "border-cad-green/60 text-cad-green" : "border-line text-slate-500"}`}>
            mcp:{status.mcp.healthy ? "up" : "down"}
          </span>
        </div>
      )}
      <label className="flex items-center gap-2 font-mono text-[11px] text-slate-500">
        <span className="chip border-cad-blue/50 text-cad-blue">{role}</span>
        <select
          className="input !w-40 !py-1"
          value={DEMO_USERS.find((u) => u.name === user)?.id ?? "u_engineer_1"}
          onChange={(e) => onUserChange(e.target.value)}
        >
          {DEMO_USERS.map((u) => (
            <option key={u.id} value={u.id}>{u.name} ({u.role})</option>
          ))}
        </select>
      </label>
    </header>
  );
}
