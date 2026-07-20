import type {
  Agent,
  AgentInput,
  Attachment,
  CustomTool,
  CustomToolInput,
  FsListing,
  GraphSpec,
  Meta,
  Metrics,
  Run,
  RunDetail,
  SuggestedModel,
  ToolDraft,
  ToolTestResult,
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

async function requestForm<T>(path: string, form: FormData): Promise<T> {
  // No Content-Type header — the browser sets the multipart boundary itself.
  const res = await fetch(path, { method: "POST", body: form });
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
  return (await res.json()) as T;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),

  listModels: () => request<SuggestedModel[]>("/api/models"),
  createModel: (name: string) =>
    request<SuggestedModel>("/api/models", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  deleteModel: (id: number) =>
    request<void>(`/api/models/${id}`, { method: "DELETE" }),

  browseDir: (path?: string) =>
    request<FsListing>(
      `/api/fs/list${path ? `?path=${encodeURIComponent(path)}` : ""}`,
    ),

  uploadAttachment: (file: File, agentId?: number) => {
    const form = new FormData();
    form.append("file", file);
    if (agentId !== undefined) form.append("agent_id", String(agentId));
    return requestForm<Attachment>("/api/attachments", form);
  },
  listAttachments: (agentId: number) =>
    request<Attachment[]>(`/api/attachments?agent_id=${agentId}`),
  deleteAttachment: (id: number) =>
    request<void>(`/api/attachments/${id}`, { method: "DELETE" }),

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
  createRun: (payload: {
    workflow_id: number;
    task: string;
    repo_path: string;
    attachment_ids?: number[];
  }) =>
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
  retryDatadogSync: (id: number) =>
    request<Run>(`/api/runs/${id}/datadog-sync`, { method: "POST" }),
  setTimeSaved: (id: number, minutes: number | null) =>
    request<Run>(`/api/runs/${id}/time-saved`, {
      method: "PATCH",
      body: JSON.stringify({ time_saved_minutes: minutes }),
    }),

  metrics: () => request<Metrics>("/api/metrics"),

  listTools: () => request<CustomTool[]>("/api/tools"),
  createTool: (t: CustomToolInput) =>
    request<CustomTool>("/api/tools", { method: "POST", body: JSON.stringify(t) }),
  updateTool: (id: number, t: CustomToolInput) =>
    request<CustomTool>(`/api/tools/${id}`, { method: "PUT", body: JSON.stringify(t) }),
  deleteTool: (id: number, force = false) =>
    request<void>(`/api/tools/${id}${force ? "?force=true" : ""}`, {
      method: "DELETE",
    }),
  generateTool: (payload: {
    prompt: string;
    attachment_ids?: number[];
    model?: string;
  }) =>
    request<ToolDraft>("/api/tools/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  testTool: (
    id: number,
    payload: { repo_path: string; params: Record<string, unknown> },
  ) =>
    request<ToolTestResult>(`/api/tools/${id}/test`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
