import { useState } from "react";

/** "1h 30m" / "45m" — em dash when never captured. */
export function formatTimeSaved(minutes: number | null | undefined): string {
  if (minutes == null) return "—";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

/**
 * Hours + minutes entry for a run's estimated time saved.
 * Empty fields mean "no estimate": Save is disabled unless the user typed a
 * value, or clearing is allowed and an estimate already exists (Save then
 * clears it back to "not captured").
 */
export function TimeSavedEditor({
  initial,
  onSave,
  onDismiss,
  dismissLabel,
  allowClear = false,
  busy = false,
}: {
  initial: number | null;
  onSave: (minutes: number | null) => void;
  onDismiss: () => void;
  dismissLabel: string;
  allowClear?: boolean;
  busy?: boolean;
}) {
  const [hours, setHours] = useState(
    initial != null ? String(Math.floor(initial / 60)) : "",
  );
  const [mins, setMins] = useState(initial != null ? String(initial % 60) : "");

  const empty = hours.trim() === "" && mins.trim() === "";
  const h = Number(hours || 0);
  const m = Number(mins || 0);
  const valid =
    Number.isInteger(h) && Number.isInteger(m) && h >= 0 && m >= 0 && m < 60;
  const value = empty ? null : h * 60 + m;
  const canSave = valid && (value !== null || (allowClear && initial !== null));

  return (
    <div className="time-saved-editor">
      <label>
        <input
          type="number"
          min={0}
          value={hours}
          onChange={(e) => setHours(e.target.value)}
          disabled={busy}
        />
        hours
      </label>
      <label>
        <input
          type="number"
          min={0}
          max={59}
          value={mins}
          onChange={(e) => setMins(e.target.value)}
          disabled={busy}
        />
        minutes
      </label>
      <button
        className="primary"
        disabled={!canSave || busy}
        onClick={() => onSave(value)}
      >
        Save
      </button>
      <button disabled={busy} onClick={onDismiss}>
        {dismissLabel}
      </button>
    </div>
  );
}
