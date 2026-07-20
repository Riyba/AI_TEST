import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api";
import type { Meta } from "./types";
import SettingsMenu from "./SettingsMenu";
import AgentsPage from "./pages/AgentsPage";
import MetricsPage from "./pages/MetricsPage";
import RunDetailPage from "./pages/RunDetailPage";
import RunLaunchPage from "./pages/RunLaunchPage";
import RunsPage from "./pages/RunsPage";
import WorkflowEditorPage from "./pages/WorkflowEditorPage";
import WorkflowsPage from "./pages/WorkflowsPage";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
  }, []);

  return (
    <div className="app">
      <nav className="sidebar">
        <h1 className="logo">
          SDLC<span>Agent Studio</span>
        </h1>
        <NavLink to="/workflows">Workflows</NavLink>
        <NavLink to="/agents">Agents</NavLink>
        <NavLink to="/runs">Runs</NavLink>
        <NavLink to="/metrics">Metrics</NavLink>
        <div className="sidebar-footer">
          {meta && !meta.api_key_configured && (
            <div className="warn">ANTHROPIC_API_KEY not set</div>
          )}
          <SettingsMenu />
          <div className="muted small">UK DevOps</div>
        </div>
      </nav>
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/workflows" replace />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
          <Route path="/workflows/:id" element={<WorkflowEditorPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/new" element={<RunLaunchPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/metrics" element={<MetricsPage />} />
        </Routes>
      </main>
    </div>
  );
}
