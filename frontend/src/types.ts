// Mirrors backend/app/schemas.py and app/graph/spec.py

export type NodeType = "agent" | "orchestrator" | "tool" | "condition" | "approval";
export type PredicateKind = "output_contains" | "output_not_contains" | "tool_success";

export interface Predicate {
  kind: PredicateKind;
  value: string;
  node_id?: string | null;
}

export interface NodeSpec {
  id: string;
  type: NodeType;
  name: string;
  position: { x: number; y: number };
  agent_id?: number | null;
  prompt?: string;
  team?: number[];
  tool?: string | null;
  params?: Record<string, unknown>;
  require_approval?: boolean;
  predicate?: Predicate | null;
  message?: string;
}

export interface EdgeSpec {
  source: string;
  target: string;
  label?: "true" | "false" | null;
}

export interface GraphSpec {
  entry: string;
  nodes: NodeSpec[];
  edges: EdgeSpec[];
}

export interface Agent {
  id: number;
  name: string;
  role: string;
  system_prompt: string;
  model: string;
  max_turns: number;
  max_tokens: number;
  tools: string[];
  require_approval: boolean;
  is_template: boolean;
  created_at: string;
  updated_at: string;
}

export type AgentInput = Omit<Agent, "id" | "is_template" | "created_at" | "updated_at">;

export interface Attachment {
  id: number;
  agent_id: number | null;
  run_id: number | null;
  filename: string;
  mime_type: string;
  kind: "image" | "pdf" | "text";
  size_bytes: number;
  created_at: string;
}

export interface Workflow {
  id: number;
  name: string;
  description: string;
  graph: GraphSpec | Record<string, never>;
  is_template: boolean;
  created_at: string;
  updated_at: string;
}

export type RunStatus =
  | "pending"
  | "running"
  | "waiting_approval"
  | "succeeded"
  | "failed"
  | "rejected"
  | "cancelled";

export interface Run {
  id: number;
  workflow_id: number;
  workflow_name: string;
  status: RunStatus;
  input: { task?: string; repo_path?: string };
  error: string | null;
  total_input_tokens: number;
  total_output_tokens: number;
  /** null = the user never captured an estimate for this run */
  time_saved_minutes: number | null;
  /** true once the run's metrics were accepted by Datadog */
  synced_to_datadog: boolean;
  created_at: string;
  finished_at: string | null;
}

export interface MetricsTotals {
  runs: number;
  runs_by_status: Record<string, number>;
  input_tokens: number;
  output_tokens: number;
  time_saved_minutes: number;
  runs_with_time_saved: number;
}

export interface DayMetrics {
  date: string;
  runs: number;
  input_tokens: number;
  output_tokens: number;
  time_saved_minutes: number;
  runs_with_time_saved: number;
}

export interface WorkflowMetrics {
  workflow_name: string;
  runs: number;
  succeeded: number;
  input_tokens: number;
  output_tokens: number;
  time_saved_minutes: number;
  runs_with_time_saved: number;
}

export interface AgentMetrics {
  agent: string;
  steps: number;
  runs: number;
  input_tokens: number;
  output_tokens: number;
}

export interface Metrics {
  totals: MetricsTotals;
  by_day: DayMetrics[];
  by_workflow: WorkflowMetrics[];
  by_agent: AgentMetrics[];
}

export interface RunStep {
  id: number;
  node_id: string;
  node_type: NodeType;
  name: string;
  status: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  tool_calls: Array<{
    tool: string;
    params: Record<string, unknown>;
    success: boolean;
    output: string;
  }>;
  input_tokens: number;
  output_tokens: number;
  started_at: string;
  finished_at: string | null;
}

export interface RunArtifact {
  id: number;
  name: string;
  kind: string;
  path: string | null;
  content: string;
  created_at: string;
}

export interface RunDetail extends Run {
  steps: RunStep[];
  artifacts: RunArtifact[];
  attachments: Attachment[];
}

export interface RunEvent {
  seq: number;
  run_id: number;
  type: string;
  ts: number;
  [key: string]: unknown;
}

export interface ApprovalPayload {
  kind: "approval" | "tool_approval";
  node_id: string;
  node_name: string;
  message: string;
  last_output?: string;
  tool?: string;
  params?: Record<string, string>;
}

export interface ToolMeta {
  name: string;
  description: string;
  mutating: boolean;
  input_schema: Record<string, unknown>;
  /** false for user-defined tools (editable); true for read-only builtins */
  builtin: boolean;
}

export interface CustomTool {
  id: number;
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  mutating: boolean;
  source_code: string;
  created_at: string;
  updated_at: string;
}

export type CustomToolInput = Omit<
  CustomTool,
  "id" | "created_at" | "updated_at"
>;

export interface ToolDraft {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  mutating: boolean;
  source_code: string;
}

export interface ToolTestResult {
  success: boolean;
  output: string;
}

export interface ToolExport {
  format: "tool";
  version: number;
  tool: CustomToolInput;
}

export interface AgentExport {
  format: "agent";
  version: number;
  agent: AgentInput;
  tools: CustomToolInput[];
}

export interface WorkflowExport {
  format: "workflow";
  version: number;
  workflow: { name: string; description: string; graph: GraphSpec | Record<string, never> };
  agents: Array<AgentInput & { id: number }>;
  tools: CustomToolInput[];
}

export interface SuggestedModel {
  id: number;
  name: string;
  created_at: string;
}

export interface Meta {
  models: string[];
  tools: ToolMeta[];
  project_roots: string[];
  api_key_configured: boolean;
  datadog_configured: boolean;
}

export interface FsEntry {
  name: string;
  path: string;
  is_git_repo: boolean;
}

export interface FsListing {
  path: string;
  parent: string | null;
  is_git_repo: boolean;
  entries: FsEntry[];
}
