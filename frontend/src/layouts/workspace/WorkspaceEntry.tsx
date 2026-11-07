import WorkspaceLayout from "../WorkspaceLayout";
import WorkspaceShellBridge from "./WorkspaceShellBridge";
import { isNewShellEnabled } from "./workspaceShellData";

/**
 * Selects the workspace shell for the authenticated routes. The existing layout stays the default; the redesigned shell
 * is used only when VITE_DEALSFLO_NEW_SHELL is "true". Both render <Outlet />, so routes are unchanged.
 */
export default function WorkspaceEntry() {
  return isNewShellEnabled() ? <WorkspaceShellBridge /> : <WorkspaceLayout />;
}
