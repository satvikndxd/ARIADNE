import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/overview", label: "Home", key: "OVW" },
  { to: "/revisions", label: "Revisions", key: "REV" },
  { to: "/components", label: "Components", key: "CMP" },
  { to: "/dependencies", label: "Dependencies", key: "DEP" },
  { to: "/standards", label: "Standards", key: "STD" },
  { to: "/findings", label: "Findings", key: "FND" },
  { to: "/chat", label: "Chat", key: "CHT" },
  { to: "/audit", label: "Audit", key: "AUD" },
  { to: "/evaluation", label: "Evaluation", key: "EVL" },
];

export function Sidebar({ projectId }: { projectId: string }) {
  return (
    <aside className="w-52 shrink-0 border-r border-line bg-ink-900 flex flex-col">
      <div className="px-4 py-4 border-b border-line">
        <div className="font-mono text-[15px] tracking-[0.3em] text-slate-100">ARIADNE</div>
        <div className="text-[10.5px] text-slate-500 font-mono mt-1">trace what changed · understand what follows</div>
      </div>
      <nav className="flex-1 py-2 overflow-y-auto scroll-thin">
        {LINKS.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-1.5 font-mono text-[12px] border-l-2 ${
                isActive
                  ? "border-cad-orange text-slate-100 bg-ink-800/70"
                  : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-ink-800/40"
              }`
            }
          >
            <span className="text-[10px] text-slate-600 w-7">{l.key}</span>
            {l.label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-line px-4 py-3">
        <div className="text-[10px] uppercase tracking-wider text-slate-600 font-mono">project</div>
        <div className="text-[12.5px] text-slate-200 font-mono mt-0.5 truncate" title={projectId}>
          Orion EV
        </div>
        <div className="text-[10px] text-slate-600 font-mono mt-1">{projectId}</div>
      </div>
    </aside>
  );
}
