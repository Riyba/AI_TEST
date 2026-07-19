import { useEffect, useRef, useState } from "react";
import { setTheme, useTheme } from "./theme";

export default function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const [theme] = useTheme();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="settings" ref={ref}>
      <button
        className="settings-trigger"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        Settings
      </button>
      {open && (
        <div className="settings-menu" role="menu">
          <div className="settings-label">Theme</div>
          <div className="segmented">
            <button
              className={theme === "light" ? "on" : ""}
              onClick={() => setTheme("light")}
            >
              Light
            </button>
            <button
              className={theme === "dark" ? "on" : ""}
              onClick={() => setTheme("dark")}
            >
              Dark
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
