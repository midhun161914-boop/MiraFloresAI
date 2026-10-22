// The trace drawer is addressed by the URL (?trace=F1040.1a&tv=v2), so any
// number anywhere is one click from its evidence and its math, the state is
// shareable, and Back closes it.
import { useCallback } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

export function useTrace() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const key = params.get("trace");
  const version = params.get("tv") ?? undefined;

  const href = useCallback((k: string, v?: string) => {
    const p = new URLSearchParams(location.search);
    p.set("trace", k);
    if (v) p.set("tv", v); else p.delete("tv");
    return `${location.pathname}?${p.toString()}`;
  }, [location.pathname, location.search]);

  /** A link that keeps the drawer open on the destination (e.g. open a source document). */
  const keepOpen = useCallback((to: string) => {
    if (!key) return to;
    const [path, search = ""] = to.split("?");
    const p = new URLSearchParams(search);
    p.set("trace", key);
    if (version) p.set("tv", version);
    return `${path}?${p.toString()}`;
  }, [key, version]);

  const open = useCallback((k: string, v?: string) => navigate(href(k, v)), [navigate, href]);
  const close = useCallback(() => {
    const p = new URLSearchParams(params);
    p.delete("trace");
    p.delete("tv");
    setParams(p);
  }, [params, setParams]);

  return { key, version, href, open, close, keepOpen };
}
