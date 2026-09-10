import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../lib/api";
import type { DocumentOut } from "../types/api";

export function DocumentViewer({ doc }: { doc: DocumentOut }) {
  const chunks = useQuery({ queryKey: ["chunks", doc.id], queryFn: () => api.documentChunks(doc.id) });
  const [page, setPage] = useState(1);
  const pages = Array.from({ length: doc.pages }, (_, i) => i + 1);
  const pageChunks = (chunks.data?.chunks ?? []).filter((c) => c.page === page);

  return (
    <div className="flex h-full min-h-0">
      <div className="w-40 shrink-0 border-r border-line overflow-y-auto scroll-thin">
        <div className="panel-title">pages</div>
        {pages.map((p) => (
          <button key={p} onClick={() => setPage(p)}
            className={`w-full text-left px-3 py-1.5 font-mono text-[11.5px] ${page === p ? "bg-ink-800 text-cad-blue" : "text-slate-400 hover:text-slate-200"}`}>
            p.{p}
          </button>
        ))}
      </div>
      <div className="flex-1 min-w-0 overflow-y-auto scroll-thin bg-[#f4f4f1] relative">
        <div className="p-8 text-[#14181e] font-serif text-[12.5px] leading-relaxed min-h-full">
          {pageChunks.map((c) => (
            <div key={c.id} className="mb-3">
              {c.section && <div className="font-mono text-[10px] text-[#6b7480] mb-0.5">§{c.section}</div>}
              <div className={(c.metadata as { requirement_code?: string })?.requirement_code ? "border border-[#c8ccd2] p-2" : ""}>
                {c.text}
              </div>
            </div>
          ))}
          {!pageChunks.length && <div className="text-[#6b7480] font-mono text-[11px]">no extracted blocks on this page</div>}
        </div>
      </div>
      <div className="w-72 shrink-0 border-l border-line overflow-y-auto scroll-thin">
        <div className="panel-title">provenance</div>
        <div className="kv"><span>authority</span><span>{doc.authority}</span></div>
        <div className="kv"><span>type</span><span>{doc.document_type}</span></div>
        <div className="kv"><span>revision</span><span>{doc.doc_revision || "—"}</span></div>
        <div className="kv"><span>chunks</span><span>{doc.chunk_count}</span></div>
        <div className="kv"><span>source</span><span className="!text-[10.5px]">{doc.source}</span></div>
        {doc.authority !== "synthetic" && (
          <div className="px-3 py-2 text-[10.5px] text-cad-amber border-b border-line">
            external/untrusted authority: excluded from evidence synthesis by policy.
          </div>
        )}
        {pageChunks.map((c) => (
          <div key={c.id} className="px-3 py-1.5 border-b border-line/50 font-mono text-[10px] text-slate-500">
            {c.id.slice(0, 10)} · p.{c.page} §{c.section || "—"}
            {c.bbox ? ` · bbox ${Math.round(c.bbox.x)},${Math.round(c.bbox.y)},${Math.round(c.bbox.width)}×${Math.round(c.bbox.height)}pt` : ""}
          </div>
        ))}
      </div>
    </div>
  );
}
