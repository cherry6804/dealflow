import { useEffect, useState } from "react";

export type ViewportBand = "mobile" | "tablet" | "desktop";

const MOBILE_QUERY = "(max-width: 767.98px)";
const TABLET_QUERY = "(min-width: 768px) and (max-width: 1023.98px)";

function readBand(): ViewportBand {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "desktop";
  if (window.matchMedia(MOBILE_QUERY).matches) return "mobile";
  if (window.matchMedia(TABLET_QUERY).matches) return "tablet";
  return "desktop";
}

/**
 * Current layout band, following the design-system breakpoints: mobile below 768px, tablet 768 to 1023px, desktop above.
 * Desktop is the fallback where matchMedia is unavailable.
 */
export function useViewport(): ViewportBand {
  const [band, setBand] = useState<ViewportBand>(readBand);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const queries = [window.matchMedia(MOBILE_QUERY), window.matchMedia(TABLET_QUERY)];
    const update = () => setBand(readBand());
    queries.forEach((query) => query.addEventListener("change", update));
    return () => queries.forEach((query) => query.removeEventListener("change", update));
  }, []);

  return band;
}
