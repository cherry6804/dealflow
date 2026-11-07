import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { resolveSpaceLocation } from "./spaceConfig";
import { SpaceLayout } from "./SpaceLayout";

/**
 * Wraps the routed page with the space layout when the path belongs to a space. Other routes render unchanged, so
 * existing pages keep their own layout until they are migrated. The space is derived from the route, so direct links,
 * reloads and browser back/forward all show the correct space and tab.
 */
export function SpaceFrame({
  children,
  navigationSuffix,
  basePath = "",
}: {
  children: ReactNode;
  navigationSuffix: string;
  basePath?: string;
}) {
  const { pathname: fullPath } = useLocation();
  const pathname = basePath && fullPath.startsWith(basePath) ? fullPath.slice(basePath.length) || "/" : fullPath;
  const resolved = resolveSpaceLocation(pathname);
  if (!resolved) return <>{children}</>;
  const { space, tab } = resolved;
  return (
    <SpaceLayout
      space={space}
      activeTab={tab}
      navigationLabel={`${space.label} ${navigationSuffix}`}
      basePath={basePath}
    >
      <div key={pathname} className="df-page-enter">
        {children}
      </div>
    </SpaceLayout>
  );
}
