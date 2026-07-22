import { useEffect, useLayoutEffect, useRef, useState } from "react";

/**
 * A kebab (⋯) trigger that opens a dropdown of secondary actions. Children are
 * rendered as a function so callers can build their own items (dividers, danger
 * styling, conditional entries) while still getting automatic close-on-click.
 * Follows the same click-outside / Escape behaviour as SettingsMenu.
 */
export default function OverflowMenu({
  label = "More actions",
  children,
}: {
  label?: string;
  children: (close: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [dropUp, setDropUp] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Flip the menu above the trigger when it would otherwise overflow the bottom
  // of the viewport. Measured before paint to avoid a visible jump.
  useLayoutEffect(() => {
    if (!open) return;
    const trigger = ref.current;
    const menu = menuRef.current;
    if (!trigger || !menu) return;
    const triggerRect = trigger.getBoundingClientRect();
    const menuHeight = menu.offsetHeight;
    const spaceBelow = window.innerHeight - triggerRect.bottom;
    const spaceAbove = triggerRect.top;
    // Drop up only if it doesn't fit below and there's more room above.
    setDropUp(spaceBelow < menuHeight + 12 && spaceAbove > spaceBelow);
  }, [open]);

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
    <div className="overflow" ref={ref}>
      <button
        className="overflow-trigger"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        title={label}
      >
        ⋯
      </button>
      {open && (
        <div
          className={dropUp ? "overflow-menu drop-up" : "overflow-menu"}
          role="menu"
          ref={menuRef}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}
