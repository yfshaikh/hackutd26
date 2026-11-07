// Light / dark / follow system. Stored per viewer; storage may be unavailable.

export type ThemePref = "system" | "light" | "dark";
const KEY = "cc-theme";

export function loadTheme(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* storage blocked */
  }
  return "system";
}

export function applyTheme(p: ThemePref) {
  const root = document.documentElement;
  if (p === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", p);
  try {
    localStorage.setItem(KEY, p);
  } catch {
    /* storage blocked */
  }
}
