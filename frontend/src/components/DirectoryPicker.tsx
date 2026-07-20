import { useEffect, useState } from "react";
import { api } from "../api";
import type { FsListing } from "../types";

/**
 * Modal filesystem browser for choosing a repository directory.
 *
 * Single-click a folder to navigate into it; "Use this folder" selects the
 * directory currently shown. Folders that are git repositories are flagged.
 */
export default function DirectoryPicker({
  initialPath,
  onSelect,
  onClose,
}: {
  initialPath?: string;
  onSelect: (path: string) => void;
  onClose: () => void;
}) {
  const [listing, setListing] = useState<FsListing | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = (path?: string) => {
    setLoading(true);
    setError("");
    api
      .browseDir(path)
      .then(setListing)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load(initialPath || undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 style={{ margin: 0 }}>Choose repository folder</h3>
          <button onClick={onClose} title="Close">
            ✕
          </button>
        </div>
        <div className="dir-current">{listing?.path ?? "…"}</div>
        {error && <div className="error-box">{error}</div>}
        <div className="dir-list">
          {listing?.parent && (
            <button className="dir-entry" onClick={() => load(listing.parent!)}>
              📁 ..
            </button>
          )}
          {listing?.entries.map((entry) => (
            <button
              key={entry.path}
              className="dir-entry"
              onClick={() => load(entry.path)}
            >
              <span>{entry.is_git_repo ? "📦" : "📁"} {entry.name}</span>
              {entry.is_git_repo && <span className="muted small">git repo</span>}
            </button>
          ))}
          {listing && listing.entries.length === 0 && (
            <p className="muted small" style={{ padding: "6px 10px", margin: 0 }}>
              No subfolders here.
            </p>
          )}
        </div>
        <div className="modal-footer">
          <span className="muted small grow">
            {listing?.is_git_repo
              ? "This folder is a git repository."
              : " "}
          </span>
          <button onClick={onClose}>Cancel</button>
          <button
            className="primary"
            disabled={!listing || loading}
            onClick={() => listing && onSelect(listing.path)}
          >
            Use this folder
          </button>
        </div>
      </div>
    </div>
  );
}
