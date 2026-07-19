import type {
  Agent,
  AgentInput,
  GraphSpec,
  Meta,
  Metrics,
  Run,
  RunDetail,
  Workflow,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),

  listAgents: () => request<Agent[]>("/api/agents"),
  createAgent: (a: AgentInput) =>
    request<Agent>("/api/agents", { method: "POST", body: JSON.stringify(a) }),
  updateAgent: (id: number, a: AgentInput) =>
    request<Agent>(`/api/agents/${id}`, { method: "PUT", body: JSON.stringify(a) }),
  deleteAgent: (id: number) =>
    request<void>(`/api/agents/${id}`, { method: "DELETE" }),

  listWorkflows: () => request<Workflow[]>("/api/workflows"),
  getWorkflow: (id: number) => request<Workflow>(`/api/workflows/${id}`),
  createWorkflow: (w: { name: string; description: string; graph: GraphSpec | Record<string, never> }) =>
    request<Workflow>("/api/workflows", { method: "POST", body: JSON.stringify(w) }),
  updateWorkflow: (
    id: number,
    w: { name: string; description: string; graph: GraphSpec | Record<string, never> },
  ) =>
    request<Workflow>(`/api/workflows/${id}`, {
      method: "PUT",
      body: JSON.stringify(w),
    }),
  deleteWorkflow: (id: number) =>
    request<void>(`/api/workflows/${id}`, { method: "DELETE" }),
  cloneWorkflow: (id: number) =>
    request<Workflow>(`/api/workflows/${id}/clone`, { method: "POST" }),

  listRuns: () => request<Run[]>("/api/runs"),
  getRun: (id: number) => request<RunDetail>(`/api/runs/${id}`),
  createRun: (payload: { workflow_id: number; task: string; repo_path: string }) =>
    request<Run>("/api/runs", { method: "POST", body: JSON.stringify(payload) }),
  submitApproval: (
    id: number,
    payload: { decision: "approve" | "reject"; note?: string; edited_output?: string | null },
  ) =>
    request<Run>(`/api/runs/${id}/approval`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  cancelRun: (id: number) =>
    request<Run>(`/api/runs/${id}/cancel`, { method: "POST" }),
  setTimeSaved: (id: number, minutes: number | null) =>
    request<Run>(`/api/runs/${id}/time-saved`, {
      method: "PATCH",
      body: JSON.stringify({ time_saved_minutes: minutes }),
    }),

  metrics: () => request<Metrics>("/api/metrics"),
};
