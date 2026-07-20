import { useEffect, useState } from "react";
import { api } from "../api";
import DirectoryPicker from "../components/DirectoryPicker";
import type { CustomTool, CustomToolInput, Meta, ToolMeta } from "../types";

const STARTER_SCHEMA = {
  type: "object",
  properties: {
    text: { type: "string", description: "Some input for the tool" },
  },
  required: ["text"],
};

const STARTER_CODE = `def run(params: dict) -> str:
    """Custom tool entry point.

    Runs in an isolated subprocess whose working directory is the target
    repository. Read inputs from params; return a string result. Raise to
    signal failure (or return a (False, "message") tuple).
    """
    text = params.get("text", "")
    return f"Received: {text}"
`;

const EMPTY: CustomToolInput = {
  name: "",
  description: "",
  input_schema: STARTER_SCHEMA,
  mutating: false,
  source_code: STARTER_CODE,
};

const HELP = {
  name: "Lowercase snake_case identifier the AI uses to call the tool (e.g. jira_lookup). Must be unique and not clash with a builtin.",
  description:
    "One sentence telling the AI what the tool does and when to use it. The model reads this to decide whether to call the tool.",
  mutating:
    "Turn on if the tool writes files, runs commands, or has any side effect. Mutating tools are gated by safe mode and approval steps, exactly like builtin ⚠ tools.",
  input_schema:
    "JSON Schema (type: object) describing the tool's parameters. Each property becomes an argument the AI fills in.",
  source_code:
    "Python that defines def run(params: dict) -> str. It runs in an isolated subprocess (repo as working dir, secrets stripped, timeout + resource limits). Standard library and installed packages are available.",
  ai: "Describe the tool in plain English and let the AI draft the code, schema, and settings for you to review. Attach API docs or examples to guide it.",
  model:
    "Which AI model builds the draft — its \"brain\". Smarter models give better results but are slower and cost more; smaller ones are fast and cheap. Pick a suggestion or type a model name.",
};

function Info({ text }: { text: string }) {
  return (
    <span className="info-icon" tabIndex={0} aria-label={text}>
      i<span className="info-tip" role="tooltip">{text}</span>
    </span>
  );
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "{}";
  }
}

export default function ToolsPage() {
  const [tools, setTools] = useState<CustomTool[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [editing, setEditing] = useState<{ id: number | null; data: CustomToolInput } | null>(null);
  const [schemaText, setSchemaText] = useState("");
  const [error, setError] = useState("");

  // AI-build panel state.
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiModel, setAiModel] = useState("claude-sonnet-5");
  const [aiFiles, setAiFiles] = useState<{ id: number; filename: string }[]>([]);
  const [generating, setGenerating] = useState(false);

  // Test panel state.
  const [testRepo, setTestRepo] = useState("");
  const [testParams, setTestParams] = useState("{}");
  const [testResult, setTestResult] = useState<{ success: boolean; output: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const [showPicker, setShowPicker] = useState(false);

  const reload = () => api.listTools().then(setTools).catch((e) => setError(e.message));

  useEffect(() => {
    reload();
    api.meta().then(setMeta).catch(() => undefined);
  }, []);

  const builtins: ToolMeta[] = (meta?.tools ?? []).filter((t) => t.builtin);

  const openEditor = (tool: CustomTool | null) => {
    setError("");
    setTestResult(null);
    setTestParams("{}");
    setAiPrompt("");
    setAiFiles([]);
    if (tool === null) {
      setEditing({ id: null, data: { ...EMPTY } });
      setSchemaText(prettyJson(STARTER_SCHEMA));
    } else {
      setEditing({
        id: tool.id,
        data: {
          name: tool.name,
          description: tool.description,
          input_schema: tool.input_schema,
          mutating: tool.mutating,
          source_code: tool.source_code,
        },
      });
      setSchemaText(prettyJson(tool.input_schema));
    }
  };

  const set = (patch: Partial<CustomToolInput>) =>
    setEditing((cur) => (cur ? { ...cur, data: { ...cur.data, ...patch } } : cur));

  const parseSchema = (): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(schemaText);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        throw new Error("must be a JSON object");
      }
      return parsed;
    } catch (e) {
      setError(`Invalid parameters JSON: ${(e as Error).message}`);
      return null;
    }
  };

  const save = async () => {
    if (!editing) return;
    setError("");
    const schema = parseSchema();
    if (!schema) return;
    const data = { ...editing.data, input_schema: schema };
    try {
      const saved =
        editing.id === null
          ? await api.createTool(data)
          : await api.updateTool(editing.id, data);
      await reload();
      openEditor(saved); // keep the (now-saved) tool open so Test is available
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async (tool: CustomTool) => {
    setError("");
    try {
      await api.deleteTool(tool.id);
      if (editing?.id === tool.id) setEditing(null);
      reload();
    } catch (e) {
      const msg = (e as Error).message;
      if (/force=true/.test(msg) && confirm(`${msg}\n\nDelete anyway?`)) {
        try {
          await api.deleteTool(tool.id, true);
          if (editing?.id === tool.id) setEditing(null);
          reload();
        } catch (e2) {
          setError((e2 as Error).message);
        }
      } else {
        setError(msg);
      }
    }
  };

  const uploadRefFile = async (file: File) => {
    setError("");
    try {
      const att = await api.uploadAttachment(file); // staged (no owner)
      setAiFiles((f) => [...f, { id: att.id, filename: att.filename }]);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const generate = async () => {
    if (!aiPrompt.trim()) return;
    setError("");
    setGenerating(true);
    try {
      const draft = await api.generateTool({
        prompt: aiPrompt,
        attachment_ids: aiFiles.map((f) => f.id),
        model: aiModel,
      });
      set({
        name: draft.name,
        description: draft.description,
        mutating: draft.mutating,
        source_code: draft.source_code,
        input_schema: draft.input_schema,
      });
      setSchemaText(prettyJson(draft.input_schema));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const runTest = async () => {
    if (!editing || editing.id === null) return;
    setError("");
    setTestResult(null);
    let params: Record<string, unknown>;
    try {
      params = JSON.parse(testParams || "{}");
    } catch (e) {
      setError(`Invalid test params JSON: ${(e as Error).message}`);
      return;
    }
    setTesting(true);
    try {
      const res = await api.testTool(editing.id, { repo_path: testRepo, params });
      setTestResult(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div>
      <div className="toolbar">
        <h2>Tools</h2>
        <div className="spacer" />
        <button className="primary" onClick={() => openEditor(null)}>
          New tool
        </button>
      </div>
      <p className="muted small" style={{ marginTop: -6 }}>
        Custom tools are your own Python, run in an isolated subprocess and callable by any
        agent or workflow — right alongside the builtin tools.
      </p>
      {error && <div className="error-box">{error}</div>}

      {editing && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <h3 style={{ marginTop: 0 }}>
            {editing.id === null ? "New tool" : `Edit tool`}
          </h3>

          <div className="panel" style={{ background: "var(--surface-2, rgba(127,127,127,.06))" }}>
            <label>Ask AI to build it <Info text={HELP.ai} /></label>
            <textarea
              rows={3}
              placeholder="e.g. Look up the current weather for a city using wttr.in and return a short summary"
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
            />
            <div className="toolbar" style={{ marginTop: 8, marginBottom: 0, gap: 8, flexWrap: "wrap" }}>
              <span className="model-field">
                <label>Model <Info text={HELP.model} /></label>
                <input
                  value={aiModel}
                  onChange={(e) => setAiModel(e.target.value)}
                  list="model-suggestions"
                  placeholder="e.g. claude-sonnet-5"
                />
                <datalist id="model-suggestions">
                  {(meta?.models ?? []).map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
              </span>
              <label className="btn-like">
                Attach reference…
                <input
                  type="file"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) uploadRefFile(file);
                    e.target.value = "";
                  }}
                />
              </label>
              {aiFiles.map((f) => (
                <span key={f.id} className="tool-chip on" onClick={() => setAiFiles((cur) => cur.filter((x) => x.id !== f.id))}>
                  {f.filename} ✕
                </span>
              ))}
              <div className="spacer" />
              <button className="primary" onClick={generate} disabled={generating || !aiPrompt.trim()}>
                {generating ? "Generating…" : "Generate draft"}
              </button>
            </div>
            <p className="muted small" style={{ marginBottom: 0 }}>
              The draft fills the form below. Review and edit it before saving — nothing runs until you do.
            </p>
          </div>

          <div className="form-grid" style={{ marginTop: 12 }}>
            <div>
              <label>Name <Info text={HELP.name} /></label>
              <input
                value={editing.data.name}
                onChange={(e) => set({ name: e.target.value })}
                placeholder="e.g. jira_lookup"
              />
            </div>
            <div className="checkbox-row" style={{ alignItems: "center" }}>
              <input
                id="mutating" type="checkbox"
                checked={editing.data.mutating}
                onChange={(e) => set({ mutating: e.target.checked })}
              />
              <label htmlFor="mutating">
                Mutating (has side effects) <Info text={HELP.mutating} />
              </label>
            </div>
            <div className="full">
              <label>Description <Info text={HELP.description} /></label>
              <input
                value={editing.data.description}
                onChange={(e) => set({ description: e.target.value })}
                placeholder="One sentence: what it does and when to use it"
              />
            </div>
            <div className="full">
              <label>Parameters (JSON Schema) <Info text={HELP.input_schema} /></label>
              <textarea
                rows={8}
                className="mono"
                value={schemaText}
                onChange={(e) => setSchemaText(e.target.value)}
                spellCheck={false}
              />
            </div>
            <div className="full">
              <label>Python source <Info text={HELP.source_code} /></label>
              <textarea
                rows={14}
                className="mono"
                value={editing.data.source_code}
                onChange={(e) => set({ source_code: e.target.value })}
                spellCheck={false}
              />
            </div>
          </div>

          {editing.id !== null && (
            <div className="panel" style={{ marginTop: 12, background: "var(--surface-2, rgba(127,127,127,.06))" }}>
              <label>Test run</label>
              <div className="toolbar" style={{ marginTop: 6, marginBottom: 6, gap: 8, flexWrap: "wrap" }}>
                <input
                  style={{ flex: "1 1 260px" }}
                  placeholder="Repository path to run against"
                  value={testRepo}
                  onChange={(e) => setTestRepo(e.target.value)}
                />
                <button onClick={() => setShowPicker(true)}>Browse…</button>
              </div>
              <label className="muted small">Params (JSON)</label>
              <textarea
                rows={3}
                className="mono"
                value={testParams}
                onChange={(e) => setTestParams(e.target.value)}
                spellCheck={false}
              />
              <div className="toolbar" style={{ marginTop: 8, marginBottom: 0 }}>
                <button className="primary" onClick={runTest} disabled={testing || !testRepo.trim()}>
                  {testing ? "Running…" : "Run test"}
                </button>
              </div>
              {testResult && (
                <div style={{ marginTop: 10 }}>
                  <span className={`badge ${testResult.success ? "" : "danger"}`}>
                    {testResult.success ? "success" : "failed"}
                  </span>
                  <pre className="output-block" style={{ marginTop: 6 }}>{testResult.output}</pre>
                </div>
              )}
            </div>
          )}

          <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
            <button className="primary" onClick={save} disabled={!editing.data.name.trim()}>
              Save
            </button>
            <button onClick={() => setEditing(null)}>Close</button>
          </div>
        </div>
      )}

      <div className="card-list">
        {tools.map((tool) => (
          <div className="card" key={tool.id}>
            <div className="grow">
              <h4>
                {tool.name} {tool.mutating && <span className="badge danger">⚠ mutating</span>}
              </h4>
              <p>{tool.description || <span className="muted">No description</span>}</p>
            </div>
            <button onClick={() => openEditor(tool)}>Edit</button>
            <button className="danger" onClick={() => remove(tool)}>Delete</button>
          </div>
        ))}
        {tools.length === 0 && <p className="muted">No custom tools yet.</p>}
      </div>

      <h3 style={{ marginTop: 28 }}>Builtin tools</h3>
      <p className="muted small" style={{ marginTop: -6 }}>
        Provided by the platform and read-only. Listed here for reference.
      </p>
      <div className="card-list">
        {builtins.map((tool) => (
          <div className="card" key={tool.name}>
            <div className="grow">
              <h4>
                {tool.name}{" "}
                {tool.mutating && <span className="badge danger">⚠ mutating</span>}{" "}
                <span className="badge template">builtin</span>
              </h4>
              <p>{tool.description}</p>
            </div>
          </div>
        ))}
      </div>

      {showPicker && (
        <DirectoryPicker
          initialPath={testRepo || undefined}
          onSelect={(p) => {
            setTestRepo(p);
            setShowPicker(false);
          }}
          onClose={() => setShowPicker(false)}
        />
      )}
    </div>
  );
}
