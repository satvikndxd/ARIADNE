/** Typed REST client.  Base URL from VITE_API_BASE_URL (defaults to :8000). */
import type {
  AnalysisProgress, AnalysisResult, ChatResponse, ComponentOut, ConfirmationOut, DependencyGraph,
  DocumentOut, EvaluationRun, FindingOut, Overview, ProjectOut, RequirementOut, RevisionOut,
  Role, SearchResponse, SystemStatus,
} from "../types/api";
export type { Role } from "../types/api";

export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

const USER_KEY = "ariadne.user";
export const DEMO_USERS: { id: string; name: string; role: Role }[] = [
  { id: "u_viewer_1", name: "Dana Okoye", role: "VIEWER" },
  { id: "u_engineer_1", name: "Sam Rivera", role: "ENGINEER" },
  { id: "u_reviewer_1", name: "Dr. Lena Fischer", role: "REVIEWER" },
  { id: "u_admin_1", name: "Alex Nowak", role: "ADMIN" },
];

export function currentUser(): string {
  return localStorage.getItem(USER_KEY) ?? "u_engineer_1";
}
export function setCurrentUser(id: string): void {
  localStorage.setItem(USER_KEY, id);
}
export function currentRole(): Role {
  return DEMO_USERS.find((u) => u.id === currentUser())?.role ?? "VIEWER";
}

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number, public hint?: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      "x-ariadne-user": currentUser(),
      ...(init?.headers ?? {}),
    },
  });
  const body = (await res.json().catch(() => null)) as
    | (T & { error?: { code: string; message: string; hint?: string } })
    | null;
  if (!res.ok) {
    const err = body?.error;
    throw new ApiError(err?.code ?? "http_error", err?.message ?? `HTTP ${res.status}`, res.status, err?.hint);
  }
  return body as T;
}

const get = <T,>(p: string) => request<T>(p);
const post = <T,>(p: string, body?: unknown) =>
  request<T>(p, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const patch = <T,>(p: string, body: unknown) => request<T>(p, { method: "PATCH", body: JSON.stringify(body) });

export const api = {
  system: () => get<SystemStatus>("/system/status"),
  projects: () => get<ProjectOut[]>("/projects"),
  project: (id: string) => get<ProjectOut>(`/projects/${id}`),
  overview: (id: string) => get<Overview>(`/projects/${id}/overview`),
  revisions: (projectId: string) => get<RevisionOut[]>(`/projects/${projectId}/revisions`),
  compare: (a: string, b: string) =>
    get<{ changes: AnalysisResult["changes"]; drawing_a: { image_url: string; width_px: number; height_px: number; filename: string } | null; drawing_b: { image_url: string; width_px: number; height_px: number; filename: string } | null; alignment: Record<string, unknown> }>(
      `/revisions/compare?revision_a=${a}&revision_b=${b}`),
  startAnalysis: (body: { project_id: string; revision_a: string; revision_b: string }) =>
    post<{ analysis_id: string; status: string }>("/analysis", body),
  analyses: (projectId?: string) =>
    get<{ id: string; status: string; mode: string; created_at: string; revision_a_id: string; revision_b_id: string; summary_json: Record<string, unknown> }[]>(
      `/analysis${projectId ? `?project_id=${projectId}` : ""}`),
  analysis: (id: string) => get<AnalysisResult>(`/analysis/${id}`),
  analysisStatus: (id: string) => get<AnalysisProgress>(`/analysis/${id}/status`),
  components: (projectId?: string) => get<ComponentOut[]>(`/components${projectId ? `?project_id=${projectId}` : ""}`),
  component: (id: string) => get<ComponentOut>(`/components/${id}`),
  dependencies: (id: string, depth = 2) => get<DependencyGraph>(`/components/${id}/dependencies?depth=${depth}`),
  revisionHistory: (id: string) =>
    get<{ component_id: string; snapshots: { revision_id: string; properties: Record<string, unknown> }[]; deltas: { revision_id: string; changed_properties: Record<string, { old: unknown; new: unknown }> }[] }>(
      `/components/${id}/revision-history`),
  findings: (projectId?: string, status?: string) =>
    get<FindingOut[]>(`/findings${projectId ? `?project_id=${projectId}${status ? `&status=${status}` : ""}` : ""}`),
  findingCounts: (projectId: string) => get<Record<string, number>>(`/findings/counts?project_id=${projectId}`),
  patchFinding: (id: string, body: unknown) => patch<FindingOut>(`/findings/${id}`, body),
  documents: () => get<DocumentOut[]>("/documents"),
  documentChunks: (id: string) =>
    get<{ chunks: { id: string; page: number; section: string; text: string; bbox: BBoxLike | null; metadata: Record<string, unknown> }[] }>(
      `/documents/${id}/chunks`),
  requirements: (componentId?: string) =>
    get<RequirementOut[]>(`/requirements${componentId ? `?component_id=${componentId}` : ""}`),
  search: (body: { query: string; project_id?: string; strategy?: string; top_k?: number; filters?: Record<string, unknown>; compare_strategies?: boolean }) =>
    post<SearchResponse>("/rag/search", body),
  chat: (body: { message: string; project_id?: string; session_id?: string; revision_a?: string; revision_b?: string; component_id?: string }) =>
    post<ChatResponse>("/chat", body),
  sessions: () => get<{ id: string; title: string; created_at: string; messages: unknown[] }[]>("/chat/sessions"),
  session: (id: string) => get<{ id: string; title: string; messages: { id: string; role: string; content: string; tool_calls_json: unknown[]; evidence_json: unknown[]; pending_confirmation_id: string | null; mode: string }[] }>(
    `/chat/sessions/${id}`),
  confirmations: (status?: string) => get<ConfirmationOut[]>(`/confirmations${status ? `?status=${status}` : ""}`),
  decide: (id: string, approved: boolean, note = "") =>
    post<ConfirmationOut>(`/confirmations/${id}/decision`, { approved, note }),
  audit: (limit = 60) => get<{ events: Record<string, unknown>[] }>(`/audit?limit=${limit}`),
  toolExecutions: (limit = 40) => get<{ tool_executions: Record<string, unknown>[] }>(`/tool-executions?limit=${limit}`),
  evaluationRuns: () => get<{ runs: EvaluationRun[] }>("/evaluation/runs"),
  runEvaluation: () => post<{ status: string }>("/evaluation/run?name=manual"),
};

type BBoxLike = { x: number; y: number; width: number; height: number };
