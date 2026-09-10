/**
 * Canonical cross-app TypeScript contracts for ARIADNE.
 *
 * The runtime sources of truth are:
 *   - Python pydantic schemas   → apps/api/app/schemas/*
 *   - REST client mirror        → apps/web/src/types/api.ts
 *   - MCP registry (names/flags)→ apps/mcp-server/src/registry.ts
 * This package pins the *vocabulary* shared by all three so drift is caught in
 * review and by the parity test (apps/api/tests/test_mcp_parity.py).
 */

export const CHANGE_TYPES = [
  "GEOMETRIC_CHANGE", "DIMENSION_CHANGE", "TOLERANCE_CHANGE", "MATERIAL_CHANGE",
  "COMPONENT_ADDED", "COMPONENT_REMOVED", "FEATURE_ADDED", "FEATURE_REMOVED",
  "ANNOTATION_CHANGE", "METADATA_CHANGE",
] as const;
export type ChangeType = (typeof CHANGE_TYPES)[number];

export const SEVERITIES = ["high", "medium", "low", "info"] as const;
export type Severity = (typeof SEVERITIES)[number];

export const ROLES = ["VIEWER", "ENGINEER", "REVIEWER", "ADMIN"] as const;
export type Role = (typeof ROLES)[number];

export const RELATIONSHIP_TYPES = [
  "DEPENDS_ON", "USES", "MATES_WITH", "PART_OF", "GOVERNED_BY", "REFERENCES",
  "SUPPLIES", "ASSEMBLED_INTO",
] as const;
export type RelationshipType = (typeof RELATIONSHIP_TYPES)[number];

export const TOOL_NAMES = [
  "get_project", "get_revision", "compare_revisions", "get_component",
  "get_component_properties", "get_dependencies", "search_requirements",
  "get_requirement", "get_revision_history", "get_findings",
  "create_review_finding", "update_finding_status",
] as const;
export type ToolName = (typeof TOOL_NAMES)[number];

export const MUTATING_TOOLS: readonly ToolName[] = ["create_review_finding", "update_finding_status"];

export const ANALYSIS_STAGES = [
  "loading_revisions", "aligning_drawings", "detecting_changes", "classifying_changes",
  "mapping_components", "traversing_dependencies", "retrieving_evidence",
  "generating_impact", "preparing_review",
] as const;
export type AnalysisStage = (typeof ANALYSIS_STAGES)[number];

export interface BBox { x: number; y: number; width: number; height: number; page?: number }

export interface EvidenceProvenance {
  document_id: string | null;
  document_name: string;
  chunk_id: string | null;
  page: number | null;
  section: string;
  bbox: BBox | null;
  authority: string;
}
