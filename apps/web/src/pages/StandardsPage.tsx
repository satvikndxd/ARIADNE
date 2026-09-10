import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { DocumentViewer } from "../components/DocumentViewer";
import { SearchBar } from "../components/SearchBar";
import { api } from "../lib/api";
import type { SearchResponse } from "../types/api";

export function StandardsPage() {
  const docs = useQuery({ queryKey: ["documents"], queryFn: api.documents });
  const [docId, setDocId] = useState<string | null>(null);
  const [search, setSearch] = useState<SearchResponse | null>(null);
  const [busy, setBusy] = useState(false);

  const active = (docs.data ?? []).find((d) => d.id === docId) ?? docs.data?.[0] ?? null;

  const run = async (q: string) => {
    setBusy(true);
    try {
      setSearch(await api.search({ query: q, project_id: "proj_orion_ev", strategy: "revision_aware", top_k: 10, compare_strategies: true }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-4 py-2.5 border-b border-line bg-ink-900 flex items-center gap-3">
        <div className="w-[420px]"><SearchBar placeholder="search standards & specifications (revision-aware RAG)…" onSearch={run} busy={busy} /></div>
        <select className="input !w-72 !py-1" value={active?.id ?? ""} onChange={(e) => setDocId(e.target.value)}>
          {(docs.data ?? []).map((d) => (
            <option key={d.id} value={d.id}>{d.title} [{d.authority}]</option>
          ))}
        </select>
        {search && <span className="font-mono text-[10.5px] text-slate-500">{search.latency_ms.toFixed(0)}ms · {search.results.length} hits</span>}
      </div>

      {search ? (
        <div className="flex-1 min-h-0 overflow-y-auto scroll-thin">
          <div className="px-4 py-2 border-b border-line font-mono text-[10.5px] text-slate-500">
            planned: {JSON.stringify(search.planned_queries[0] ?? {}).slice(0, 220)}
          </div>
          {search.results.map((r) => (
            <div key={r.chunk_id ?? r.evidence_id} className="px-4 py-2.5 border-b border-line/60 hover:bg-ink-800/40">
              <div className="flex items-center gap-2 font-mono text-[11px]">
                <span className="text-cad-blue">#{r.rank}</span>
                <button className="text-slate-200 hover:text-cad-orange" onClick={() => { setDocId(r.document_id); setSearch(null); }}>
                  {r.document_name}
                </button>
                <span className="text-slate-600">§{r.section || "—"} p.{r.page}</span>
                <span className="chip border-line text-slate-500">{r.authority}</span>
                <span className="flex-1" />
                <span className="text-slate-400">score {r.score.toFixed(3)}</span>
                <span className="text-slate-600">d{r.dense_score.toFixed(2)} l{r.lexical_score.toFixed(2)} m{r.metadata_boost.toFixed(2)}</span>
              </div>
              <div className="mt-1 text-[12px] text-slate-400">{r.text}</div>
            </div>
          ))}
          {search.comparison.length > 0 && (
            <div className="px-4 py-3">
              <div className="panel-title mb-2">baseline comparison (this query)</div>
              <div className="grid grid-cols-3 gap-3">
                {search.comparison.map((c) => (
                  <div key={c.strategy} className="panel">
                    <div className="panel-title">{c.strategy}</div>
                    {c.results.map((r, i) => (
                      <div key={i} className="kv"><span className="truncate">{r.document_name} §{r.section}</span><span>{r.score.toFixed(2)}</span></div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : active ? (
        <div className="flex-1 min-h-0"><DocumentViewer doc={active} /></div>
      ) : null}
    </div>
  );
}
