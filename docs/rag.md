# RAG architecture

## Ingestion
```
PDF (pypdf) + layout sidecar (page/section/bbox in PDF points)
   → block stream (heading | paragraph | requirement | table rows)
   → chunks (section-heading enriched, ≤ ~220 tokens)
   → metadata enrichment: document_id, page, section, bbox, component_ids,
     revision, document_type, authority, requirement_code, machine rule
   → embeddings (OpenAI-compatible or deterministic hashing embedder)
   → vector store (pgvector on PostgreSQL, numpy+vector_records on SQLite)
```
Every chunk keeps provenance; the UI can point at the exact page region.
Blocks are verified against pypdf-extracted page text; unverified blocks are
flagged, not silently trusted.

## Retrieval strategies
| strategy | mechanism | role |
|---|---|---|
| `keyword` | BM25 over chunks | baseline A |
| `vector` | dense only, no filters | baseline B |
| `metadata_aware` | dense + metadata predicate + metadata boost | ablation |
| `revision_aware` | multi-query RRF + metadata predicate + revision salience; revision-scoped questions order the revision note of that revision first (metadata-first tier) | **proposed** |
| `hybrid` | RRF(keyword, metadata_aware) | ablation |

## Query planning
The raw user query always drives the primary ranking. Augmented/normative
phrasings (`… requirement specification limit clearance tolerance`),
per-component and per-relationship phrasings are emitted as *sub-queries* and
fused with reciprocal-rank fusion, so a generic vocabulary can never outrank
the actual question.

## Reranker
Transparent weighted sum, weights returned per result:
`0.45·dense + 0.25·lexical + 0.15·metadata + 0.15·fusion`, where metadata
decomposes into component (0.40), revision (0.25), document-type (0.15) and
authority (0.20) signals. A neural cross-encoder can replace it behind the
same signature.

## Prompt-injection policy
Retrieved text is wrapped in `<evidence>` fences and treated as data. Chunks
matching instruction-shaped patterns, or from untrusted authorities, are
quarantined: down-weighted, badged in the UI, and excluded from synthesis.

## Known limitations
* The offline embedder is a hashed bag-of-words projection: lexical overlap
  only. Narrative queries that need true semantic bridging underperform until
  a real embedding model is configured (`EMBEDDING_*` env vars).
* Bounding boxes exist for the synthetic corpus (layout sidecars). Real PDFs
  without a layout parser get page/section provenance only.
