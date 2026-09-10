/** Mirrors of the FastAPI schemas (single source of truth: apps/api/app/schemas). */

export type Severity = "high" | "medium" | "low" | "info";
export type FindingStatus = "open" | "needs_review" | "accepted" | "rejected" | "resolved";
export type Role = "VIEWER" | "ENGINEER" | "REVIEWER" | "ADMIN";

export interface BBox { x: number; y: number; width: number; height: number; page?: number; sheet?: string }

export interface ProjectOut {
  id: string; name: string; code: string; description: string; status: string;
  active_revision_id: string | null; stats: Record<string, number>;
}

export interface DrawingOut {
  id: string; revision_id: string; filename: string; drawing_type: string;
  width_px: number; height_px: number; image_url: string;
}

export interface RevisionOut {
  id: string; project_id: string; name: string; label: string; sequence: number;
  status: string; notes: string; created_at: string | null; drawings: DrawingOut[];
  metadata_json?: Record<string, unknown>;
}

export interface ChangeOut {
  id: string; change_type: string; component_id: string | null; component_name: string;
  title: string; old_value: string | null; new_value: string | null; unit: string;
  numeric_delta: number | null; location: BBox; confidence: number; severity: Severity;
  classification: "consequential" | "cosmetic" | "metadata"; detection_method: string;
  description: string; drawing_id: string | null; revision_a: string; revision_b: string;
  metadata: Record<string, unknown>;
}

export interface AffectedComponent {
  component_id: string; name: string; severity: Severity; reason: string;
  distance_hops: number; relationship_path: string[]; confidence: number;
  via_change_ids: string[];
}

export interface EvidenceRef {
  evidence_id: string; evidence_type: string; document_id: string | null; document_name: string;
  chunk_id: string | null; page: number | null; section: string; bbox: BBox | null;
  excerpt: string; score: number; authority: string; retrieval_strategy: string;
}

export interface DeterministicCheck {
  requirement_code: string; rule: string; description: string; result: "pass" | "fail" | "flag" | "n/a";
  margin: number | null; unit: string; inputs: Record<string, unknown>; field: string; severity: string;
}

export interface Insight {
  summary: string; potential_impact: string; reasoning: string; uncertainty: string;
  confidence: { value: number; basis: string; factors: Record<string, number> };
  grounded: boolean; mode: "demo" | "live";
}

export interface Recommendation { text: string; action_type: string; priority: Severity; grounded_in: string[] }

export interface ProposedFinding {
  title: string; severity: Severity; confidence: number; component_id: string | null;
  description: string; recommendation: string; affected_component_ids: string[];
  evidence: EvidenceRef[]; requires_confirmation: boolean;
}

export interface AnalysisResult {
  analysis_id: string; project: { id: string; name: string }; revisions: Record<string, { id: string; name: string }>;
  status: string; mode: "demo" | "live"; changes: ChangeOut[]; affected_components: AffectedComponent[];
  evidence: EvidenceRef[]; recommendations: Recommendation[]; proposed_findings: ProposedFinding[];
  insight: Insight; confidence: number; deterministic_checks: DeterministicCheck[];
  retrieval_strategies: Record<string, unknown>; latency_ms: number;
}

export interface AnalysisProgress {
  analysis_id: string; status: "queued" | "running" | "completed" | "failed";
  stage: string; progress: number; message: string;
  events: { seq: number; stage: string; message: string; payload: Record<string, unknown> }[];
}

export interface ComponentOut {
  id: string; project_id: string; name: string; code: string; type: string; subsystem: string;
  material: string; weight_g: number; description: string; properties: Record<string, unknown>;
  revision_id: string | null; finding_count: number;
}

export interface GraphNode {
  id: string; label: string; type: string; subsystem: string; material: string;
  depth: number; direction: "root" | "upstream" | "downstream" | "spec" | "assembly";
}

export interface GraphEdge {
  id: string; source_component_id: string; target_component_id: string;
  relationship_type: string; criticality: string;
}

export interface DependencyGraph {
  root_component_id: string; depth: number; nodes: GraphNode[]; edges: GraphEdge[];
  upstream: string[]; downstream: string[]; specifications: string[]; store: string;
}

export interface FindingEvidence {
  id: string; evidence_type: string; document_id: string | null; chunk_id: string | null;
  page: number | null; section: string; bbox: BBox | null; excerpt: string; score: number;
}

export interface FindingOut {
  id: string; project_id: string; revision_id: string | null; component_id: string | null;
  title: string; severity: Severity; confidence: number; description: string; recommendation: string;
  status: FindingStatus; source: string; created_by: string; reviewed_by: string | null;
  created_at: string | null; evidence: FindingEvidence[]; affected_component_ids: string[];
  component_name: string;
}

export interface DocumentOut {
  id: string; title: string; document_type: string; authority: string; pages: number;
  doc_revision: string; chunk_count: number; source: string;
}

export interface RequirementOut {
  id: string; code: string; title: string; section: string; page: number; text: string;
  applies_to_json: string[]; document_title: string;
}

export interface ScoredChunk extends EvidenceRef {
  rank: number; rerank_score: number; lexical_score: number; dense_score: number;
  metadata_boost: number; text: string;
}

export interface SearchResponse {
  query: string; strategy: string; results: ScoredChunk[];
  comparison: { strategy: string; results: ScoredChunk[] }[];
  planned_queries: Record<string, unknown>[]; latency_ms: number; empty: boolean; notice: string;
}

export interface ToolCallRecord {
  tool_name: string; arguments: Record<string, unknown>; status: string; transport: string;
  latency_ms: number; mutating: boolean; result_summary: string; error: string | null; execution_id: string;
}

export interface PendingAction {
  confirmation_id: string; tool_name: string; action_label: string; summary: string;
  payload: Record<string, unknown>; evidence: EvidenceRef[];
  affected: { component_id: string; name: string; severity: Severity }[];
}

export interface ChatResponse {
  session_id: string; message_id: string; answer: string; structured: Record<string, unknown>;
  tool_calls: ToolCallRecord[]; evidence: EvidenceRef[]; pending_action: PendingAction | null;
  mode: "demo" | "live"; grounded: boolean; insufficient_evidence: boolean; latency_ms: number;
}

export interface ChatMessageOut {
  id: string; session_id: string; role: string; content: string;
  tool_calls_json: ToolCallRecord[]; evidence_json: EvidenceRef[];
  pending_confirmation_id: string | null; mode: string; created_at: string | null;
}

export interface ConfirmationOut {
  id: string; tool_name: string; action_label: string; summary: string; status: string;
  requested_by: string; decided_by: string | null; evidence_json: EvidenceRef[];
  payload_json: Record<string, unknown>; result_json: Record<string, unknown>;
  created_at: string | null;
}

export interface SystemStatus {
  demo_mode: boolean;
  llm: { provider: string; live: boolean; model: string };
  embeddings: { provider: string; dim: number; live: boolean };
  vision: { enabled: boolean; model: string };
  vector_store: string; graph_store: string;
  mcp: { enabled: boolean; url: string; healthy: boolean };
  knowledge: { chunks: number; vectors: number };
  database: string;
}

export interface Overview {
  project: ProjectOut; revision_count: number; active_revision: string | null;
  findings_total: number; findings_by_status: Record<string, number>;
  affected_components: string[]; unresolved_changes: number;
  latest_analysis: { id: string; status: string; mode: string; summary: Record<string, unknown> } | null;
  recent_activity: { id: string; status: string; created_at: string; mode: string }[];
}

export interface EvaluationRun {
  id: string; name: string; mode: string; created_at: string; report_path: string;
  metrics: { subset: string; metric: string; value: number; n: number }[];
}
