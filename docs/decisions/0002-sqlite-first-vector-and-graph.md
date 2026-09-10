# ADR-0002 — SQLite-first storage with pgvector/Neo4j behind abstractions

**Status:** accepted.

**Context.** The prototype must run with `git clone && make seed && make dev`,
on a laptop with no infrastructure, yet scale to PostgreSQL in compose.

**Decision.** One SQLAlchemy schema portable across SQLite and PostgreSQL.
`VectorStore` protocol with `NumpyVectorStore` (vectors persisted in
`vector_records`) and `PgVectorStore` (real `vector` column, cosine).
`GraphStore` protocol with `SqlGraphStore` (BFS) and optional
`Neo4jGraphStore`. Selection is env-driven (`VECTOR_STORE`, `GRAPH_STORE`,
`auto`) and **reported in responses and `/system/status`**, never silent.

**Consequences.** + zero-infra onboarding and CI; + honest capability
discovery; − numpy store is exact search (fine at prototype scale); − Neo4j
path is exercised only when configured.
