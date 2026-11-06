# Figma reference inventory

Source: `docs/design-references/figma/complete-figma-reference.jpg` (4708 × 11318 px). Untracked in the DealFlow checkout and not committed here. The original is never modified. SHA-256 at analysis time: `8165B1F1947CC65E3B9B9089D10198F61943106C740818538DC5A196B218C8ED`.

Derived crops live outside the repository, in the working analysis folder `figma-analysis/`. Crops are estimated from the overview grid (3 columns, 8 rows). Boundaries were checked visually on two tiles only, so tile edges and counts are approximate.

## Verified at full resolution

| Ref ID | Screen | Type | Dealsflo module | Notes |
|---|---|---|---|---|
| ref-r01-c1 | All deals, desktop | Data grid list | Deals | Header with product mark, tenant switcher, global search, AI action, notifications, avatar. Sidebar (Overview, Sales, Leads, Contacts, Deals, Properties, Activities, Reports, Customize spaces). Page title, subtitle, KPI strip (open pipeline, weighted forecast, closing this month, needs attention), filter bar with search, Filter, Sort, Group, Columns, active filter chips, "Shared view" indicator, grid with pinned first column, stage badges, owner avatars, health status, pagination with rows-per-page. |
| ref-r05-c2 | All deals, tablet or narrow | Responsive list | Deals | Compact header, icon-only sidebar rail, KPI row reduced to three values, filter button group, cards-style rows instead of a wide grid, pagination. |

## Overview only (not verified at full resolution)

These are identified from the reduced overview. Each needs its full-resolution crop checked before implementation.

| Ref ID (grid position) | Screen as seen at reduced scale | Likely module |
|---|---|---|
| ref-r01-c2 | Connected pipeline, kanban board with stage columns and cards | Pipeline |
| ref-r01-c3 | Deal detail, "Meridian Tower · HQ lease", activity feed and side panels | Deals |
| ref-r02-c1 | "Good morning" dashboard: KPI cards, bar chart, activity and task lists | Dashboard |
| ref-r02-c2 | Lead inbox table with filters and status | Leads |
| ref-r02-c3 | Lead detail or intake view (uncertain) | Leads |
| ref-r03-c1 | People / contacts table | Contacts |
| ref-r03-c2 | Property portfolio, image cards with price and status | Properties |
| ref-r03-c3 | Activities, weekly calendar with activity blocks | Activities |
| ref-r04-c1 | Revenue intelligence: forecast chart and breakdown tables | Reports / analytics |
| ref-r04-c2 | Customise your workspace: space and widget configuration | Customization |
| ref-r04-c3 | AI deals table with bulk selection and column chooser popover | Deals / AI |
| ref-r05-c1, ref-r05-c3 | Mobile list and deal detail screens (uncertain) | Mobile deals |
| ref-r06 row | Further mobile and tablet variants, navigation drawers (uncertain) | Mobile shell |
| ref-r07 row | Additional screens (uncertain) | Unknown |
| ref-design-system-top | Design system sheet: foundations, colour and type specimens, controls, grids | Design system |
| ref-design-system-bottom | Design system sheet: safety and permissions, spacing, component library | Design system |

## Reusable patterns (from verified screens)

- Page header: title, one-line subtitle with counts, primary action right-aligned, secondary actions beside it.
- KPI strip: one bordered card with divided metrics, a label, a large value and a secondary delta.
- Toolbar: search field first, then filter, sort, group and columns controls. Active filters appear as removable chips below.
- Data grid: pinned first column, sticky header, status badges, avatar plus name cells, row checkboxes, pagination footer.
- Sidebar: workspace label, grouped navigation with a count badge, collapsible rail, footer card with status.
- Responsive: the sidebar becomes an icon rail, and the grid becomes stacked rows on narrow widths.

## Uncertainty

- Tile boundaries, tile count and the screen order in rows 5 to 7 are not verified.
- Colour values, the exact type scale and the spacing scale are not extracted. They must come from the design-system tiles at full resolution.
- Some labels in the reduced overview cannot be read reliably.
