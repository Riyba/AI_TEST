import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "sdlc-theme";
const EVENT = "sdlc-theme-change";

/** Light is the explicit default, regardless of OS preference. */
export function getStoredTheme(): Theme {
  return localStorage.getItem(STORAGE_KEY) === "dark" ? "dark" : "light";
}

export function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

export function setTheme(theme: Theme) {
  localStorage.setItem(STORAGE_KEY, theme);
  applyTheme(theme);
  window.dispatchEvent(new CustomEvent(EVENT));
}

/** Reactive theme value kept in sync across the app (and other tabs). */
export function useTheme(): [Theme, () => void] {
  const [theme, setThemeState] = useState<Theme>(getStoredTheme);

  useEffect(() => {
    const sync = () => setThemeState(getStoredTheme());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return [theme, () => setTheme(theme === "dark" ? "light" : "dark")];
}
