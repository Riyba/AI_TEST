import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Attachment } from "../types";

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Upload + list + remove UI for attachments.
 *
 * - With `agentId`: files are attached to that agent (loaded from and saved
 *   to the server immediately).
 * - Without `agentId`: files are uploaded as "staged" attachments; the parent
 *   receives the current list via `onChange` and passes the ids when
 *   creating a run.
 */
export default function AttachmentsEditor({
  agentId,
  onChange,
}: {
  agentId?: number;
  onChange?: (attachments: Attachment[]) => void;
}) {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (agentId !== undefined) {
      api.listAttachments(agentId).then(setAttachments).catch((e) => setError(e.message));
    }
  }, [agentId]);

  const update = (next: Attachment[]) => {
    setAttachments(next);
    onChange?.(next);
  };

  const upload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    setError("");
    try {
      const uploaded: Attachment[] = [];
      for (const file of Array.from(files)) {
        uploaded.push(await api.uploadAttachment(file, agentId));
      }
      update([...attachments, ...uploaded]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const remove = async (id: number) => {
    setError("");
    try {
      await api.deleteAttachment(id);
      update(attachments.filter((a) => a.id !== id));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="attachments">
      {error && <div className="error-box">{error}</div>}
      {attachments.map((att) => (
        <div className="attachment-row" key={att.id}>
          <span className="grow">
            {att.filename}{" "}
            <span className="muted small">
              {att.kind} · {formatBytes(att.size_bytes)}
            </span>
          </span>
          <button className="danger" onClick={() => remove(att.id)} title="Remove">
            ✕
          </button>
        </div>
      ))}
      {attachments.length === 0 && (
        <p className="muted small" style={{ margin: "4px 0" }}>
          No files attached.
        </p>
      )}
      <input
        ref={fileInput}
        type="file"
        multiple
        accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,text/*,.md,.txt,.json,.csv,.yaml,.yml,.xml,.log"
        style={{ display: "none" }}
        onChange={(e) => upload(e.target.files)}
      />
      <button disabled={busy} onClick={() => fileInput.current?.click()}>
        {busy ? "Uploading…" : "Add file"}
      </button>
    </div>
  );
}
