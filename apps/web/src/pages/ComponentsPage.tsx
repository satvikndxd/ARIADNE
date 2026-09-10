import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useOutletContext } from "react-router-dom";

import { api } from "../lib/api";

export function ComponentsPage() {
  const { projectId } = useOutletContext<{ projectId: string }>();
  const nav = useNavigate();
  const comps = useQuery({ queryKey: ["components", projectId], queryFn: () => api.components(projectId) });
  return (
    <div className="h-full overflow-auto scroll-thin">
      <table className="dense">
        <thead>
          <tr><th>component</th><th>code</th><th>subsystem</th><th>type</th><th>material</th><th>mass</th><th>findings</th></tr>
        </thead>
        <tbody>
          {(comps.data ?? []).map((c) => (
            <tr key={c.id} className="cursor-pointer" onClick={() => nav(`/components/${c.id}`)}>
              <td className="text-slate-200">{c.name}</td>
              <td className="font-mono text-[11px] text-slate-400">{c.code}</td>
              <td className="font-mono text-[11px]">{c.subsystem}</td>
              <td className="font-mono text-[11px] text-slate-400">{c.type}</td>
              <td className="font-mono text-[11px]">{c.material || "—"}</td>
              <td className="font-mono text-[11px]">{c.weight_g ? `${c.weight_g} g` : "—"}</td>
              <td className="font-mono text-[11px] text-cad-orange">{c.finding_count || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
