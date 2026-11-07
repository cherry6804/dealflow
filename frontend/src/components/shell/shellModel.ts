import type { WorkspaceModule } from "../../layouts/workspace/workspaceSpaces";

/**
 * Pure helpers for the application shell. No React, no storage, no network.
 *
 * Permissions: the session currently carries no per-user permission list, so no module is gated yet. A module that needs
 * a permission declares it in `PERMISSION_BY_MODULE`; `canAccess` decides what the shell shows. Until the backend exposes
 * permissions to the frontend, the shell must not invent them. Route guards still enforce access.
 */

/** Maps a module label to the permission key that gates it. Empty until a backend permission contract exists. */
export const PERMISSION_BY_MODULE: Readonly<Record<string, string>> = {};

export type CanAccess = (permission: string) => boolean;

export function isModuleVisible(
  module: WorkspaceModule,
  canAccess: CanAccess,
  permissionByModule: Readonly<Record<string, string>> = PERMISSION_BY_MODULE,
): boolean {
  const permission = permissionByModule[module.label];
  return permission === undefined || canAccess(permission);
}

export function filterVisibleModules(
  modules: readonly WorkspaceModule[],
  canAccess: CanAccess,
  permissionByModule: Readonly<Record<string, string>> = PERMISSION_BY_MODULE,
): WorkspaceModule[] {
  return modules.filter((module) => isModuleVisible(module, canAccess, permissionByModule));
}

/** True when `pathname` is the module route or a child of it. The root route only matches exactly. */
export function isRouteActive(pathname: string, to: string): boolean {
  if (to === "/") return pathname === "/";
  return pathname === to || pathname.startsWith(`${to}/`);
}

/** Prefixes a module route for a preview mount point. Production passes no prefix, so routes are unchanged. */
export function withBasePath(to: string, basePath = ""): string {
  if (!basePath) return to;
  return to === "/" ? basePath : `${basePath}${to}`;
}

export interface Breadcrumb {
  label: string;
  to?: string;
}

/**
 * Breadcrumb trail for the current path. The last item has no link, because it is the current page.
 * `homeLabel` is passed in already translated.
 */
export function buildBreadcrumbs(
  pathname: string,
  modules: readonly WorkspaceModule[],
  homeLabel: string,
  basePath = "",
): Breadcrumb[] {
  const crumbs: Breadcrumb[] = [{ label: homeLabel, to: withBasePath("/", basePath) }];
  const match = modules
    .filter((module) => module.to !== "/" && isRouteActive(pathname, module.to))
    .sort((a, b) => b.to.length - a.to.length)[0];
  if (match) {
    crumbs.push({ label: match.label, to: withBasePath(match.to, basePath) });
  }
  return crumbs.map((crumb, index) => (index === crumbs.length - 1 ? { label: crumb.label } : crumb));
}

export interface ShellCommand {
  id: string;
  label: string;
  group: string;
  keywords?: string;
  /** Permission that gates this command. Omit for commands every signed-in user can run. */
  permission?: string;
  run: () => void;
}

/**
 * Filters commands by a case-insensitive query. Labels that start with the query rank above labels that contain it.
 * An empty query returns every command in its original order.
 */
export function filterCommands(commands: readonly ShellCommand[], query: string): ShellCommand[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...commands];

  const scored: Array<{ command: ShellCommand; score: number }> = [];
  for (const command of commands) {
    const label = command.label.toLowerCase();
    const haystack = `${label} ${(command.keywords ?? "").toLowerCase()}`;
    if (!haystack.includes(needle)) continue;
    scored.push({ command, score: label.startsWith(needle) ? 0 : 1 });
  }
  return scored.sort((a, b) => a.score - b.score).map(({ command }) => command);
}
