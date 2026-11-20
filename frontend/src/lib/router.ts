import { useEffect, useState } from "react";

/** Minimal history router: the app has a handful of routes and no nested layouts. */
export function navigate(to: string, replace = false) {
  if (to === location.pathname + location.search) return;
  if (replace) history.replaceState(null, "", to);
  else history.pushState(null, "", to);
  window.dispatchEvent(new Event("app:navigate"));
}

export function useLocation() {
  const [loc, setLoc] = useState({ path: location.pathname, search: location.search });
  useEffect(() => {
    const on = () => setLoc({ path: location.pathname, search: location.search });
    window.addEventListener("popstate", on);
    window.addEventListener("app:navigate", on);
    return () => {
      window.removeEventListener("popstate", on);
      window.removeEventListener("app:navigate", on);
    };
  }, []);
  return loc;
}

export function setQuery(params: Record<string, string | null | undefined>, replace = true) {
  const q = new URLSearchParams(location.search);
  for (const [k, v] of Object.entries(params)) {
    if (v == null || v === "") q.delete(k);
    else q.set(k, v);
  }
  const s = q.toString();
  navigate(location.pathname + (s ? "?" + s : ""), replace);
}
