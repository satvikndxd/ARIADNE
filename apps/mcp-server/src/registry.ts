/**
 * Tool metadata — must stay in lock-step with
 * apps/api/app/services/agent/tools.py and core/security.py TOOL_POLICY.
 * `mutating: true` means the API will refuse execution without an approved
 * human confirmation (enforced server-side, twice: here and in the gateway).
 */
export interface ToolMeta {
  name: string;
  description: string;
  mutating: boolean;
  permission: string;
}

export const TOOL_META: ToolMeta[] = [
  { name: "get_project", description: "Project metadata plus revision/component/finding counts.", mutating: false, permission: "read:project_data" },
  { name: "get_revision", description: "A single revision with its drawings.", mutating: false, permission: "read:project_data" },
  { name: "compare_revisions", description: "Deterministic revision comparison: aligned image diff plus structured change list with locations and confidences.", mutating: false, permission: "read:project_data" },
  { name: "get_component", description: "Component master data (material, mass, subsystem).", mutating: false, permission: "read:project_data" },
  { name: "get_component_properties", description: "Per-revision property snapshots of a component.", mutating: false, permission: "read:project_data" },
  { name: "get_dependencies", description: "Traverse the dependency graph from a component (upstream + downstream).", mutating: false, permission: "read:project_data" },
  { name: "search_requirements", description: "Revision-aware retrieval over standards/specifications with provenance (document, section, page, bbox).", mutating: false, permission: "knowledge:search" },
  { name: "get_requirement", description: "One requirement by id or code, including its machine-readable rule.", mutating: false, permission: "knowledge:search" },
  { name: "get_revision_history", description: "Property deltas of a component across revisions.", mutating: false, permission: "read:project_data" },
  { name: "get_findings", description: "List findings of a project, optionally filtered by status.", mutating: false, permission: "read:project_data" },
  { name: "create_review_finding", description: "Create a review finding. MUTATING: requires an approved human confirmation.", mutating: true, permission: "finding:create" },
  { name: "update_finding_status", description: "Accept/reject/resolve a finding. MUTATING: reviewer role required.", mutating: true, permission: "finding:update" },
];

export const isMutating = (name: string): boolean =>
  TOOL_META.find((t) => t.name === name)?.mutating ?? false;
