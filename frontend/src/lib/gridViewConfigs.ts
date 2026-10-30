import type { TableDensity } from "../layouts/workspace/workspacePreferences";
import type { GridColumnOption } from "./gridViewPreferences";

export interface GridViewConfig {
  gridId: string;
  columnOptions: readonly GridColumnOption[];
  rowHeights: Readonly<Record<TableDensity, number>>;
}

export const LEADS_GRID_VIEW: GridViewConfig = {
  gridId: "leads",
  columnOptions: [
    { key: "lead", label: "Lead / Contact", defaultVisible: true },
    { key: "status", label: "Status", defaultVisible: true },
    { key: "interest", label: "Interest", defaultVisible: true },
    { key: "nextAction", label: "Next follow-up", defaultVisible: true },
    { key: "createdAt", label: "Created", defaultVisible: true },
  ],
  rowHeights: { comfortable: 58, compact: 42 },
};

export const DEALS_GRID_VIEW: GridViewConfig = {
  gridId: "deals",
  columnOptions: [
    { key: "customerProperty", label: "Customer / Property", defaultVisible: true },
    { key: "stage", label: "Stage", defaultVisible: true },
    { key: "expectedValue", label: "Expected value", defaultVisible: true },
    { key: "owner", label: "Owner", defaultVisible: true },
    { key: "createdAt", label: "Created", defaultVisible: true },
  ],
  rowHeights: { comfortable: 62, compact: 48 },
};

export const CONTACTS_GRID_VIEW: GridViewConfig = {
  gridId: "contacts",
  columnOptions: [
    { key: "name", label: "Contact", defaultVisible: true },
    { key: "email", label: "Email address", defaultVisible: true },
    { key: "phone", label: "Phone number", defaultVisible: true },
    { key: "createdAt", label: "Created", defaultVisible: true },
    { key: "status", label: "Status", defaultVisible: true },
  ],
  rowHeights: { comfortable: 60, compact: 48 },
};
