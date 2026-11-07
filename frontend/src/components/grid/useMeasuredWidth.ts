import { useCallback, useLayoutEffect, useState } from "react";

/**
 * Tracks the rendered width of an element. Used to stretch grid columns to the available width. Falls back to a fixed width
 * where ResizeObserver is unavailable (for example in some test environments).
 */
export function useMeasuredWidth(fallback = 1200) {
  const [width, setWidth] = useState(fallback);
  const [node, setNode] = useState<HTMLElement | null>(null);
  const ref = useCallback((element: HTMLElement | null) => setNode(element), []);

  useLayoutEffect(() => {
    if (!node) return;
    const measure = () => setWidth(node.clientWidth || fallback);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [node, fallback]);

  return [ref, width] as const;
}
