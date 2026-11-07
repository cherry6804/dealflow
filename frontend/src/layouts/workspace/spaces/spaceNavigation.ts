import { resolveSpaceLocation, type SpaceDefinition, type SpaceTab } from "./spaceConfig";

/** The tab a space's sidebar entry opens: its first tab that has a real page, not a placeholder. */
export function firstRoutableTab(space: SpaceDefinition): SpaceTab | undefined {
  return space.tabs.find((tab) => tab.to && !tab.placeholder) ?? space.tabs.find((tab) => tab.to);
}

/** Route that a space's sidebar entry opens. */
export function spaceHref(space: SpaceDefinition): string {
  return firstRoutableTab(space)?.to ?? "/";
}

/**
 * Breadcrumb trail for a space route: Home, the space, then the tab. Undefined when the path is not in any space, so
 * the shell's default trail applies.
 */
export function spaceBreadcrumbs(pathname: string, homeLabel: string, homeTo: string): Array<{ label: string; to?: string }> | undefined {
  const resolved = resolveSpaceLocation(pathname);
  if (!resolved) return undefined;
  const { space, tab } = resolved;
  if (pathname === "/") return [{ label: space.label }];
  return [{ label: homeLabel, to: homeTo }, { label: space.label, to: spaceHref(space) }, { label: tab.label }];
}
