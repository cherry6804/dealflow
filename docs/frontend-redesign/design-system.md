# Dealsflo design system

Status: single token source established. Module migration is in progress.

## Source of truth

- `frontend/src/styles/tokens.css` defines every token on `:root`. Light values are the approved brand palette, including `--df-primary: #0c66e4`. Changing a brand colour needs separate approval.
- `frontend/src/styles/theme.css` defines dark values for every colour token. It applies under `prefers-color-scheme: dark` unless the user chose light, and under `data-theme="dark"`.
- Components read tokens only. New components must not use literal colours.

Contract tests in `frontend/src/styles/designTokens.test.ts` enforce the rules below:
1. Every token referenced by the new component layer (`components/ui`, `components/shell`, the dev preview) is defined in `tokens.css`.
2. Every colour token has a dark value in `theme.css`.
3. `theme.css` defines no token that `tokens.css` does not.

## Roles

| Group | Tokens | Notes |
|---|---|---|
| Surfaces | `--df-canvas`, `--df-surface`, `--df-surface-soft`, `--df-surface-hover`, `--df-surface-selected` | Canvas is the page; surface is cards and panels; soft is inset or toolbar areas |
| Text | `--df-ink`, `--df-ink-soft`, `--df-muted`, `--df-subtle`, `--df-disabled`, `--df-on-primary` | Use ink for content; muted for helper text; subtle only for placeholders |
| Borders | `--df-border`, `--df-border-soft`, `--df-border-strong` | Hairline dividers use soft; control borders use strong |
| Action | `--df-primary`, `--df-primary-hover`, `--df-primary-active`, `--df-primary-soft`, `--df-focus-ring` | One primary action per region |
| Status | `--df-success`, `--df-warning`, `--df-danger`, `--df-info`, `--df-neutral`, `--df-purple`, `--df-teal`, `--df-orange`, each with `-soft` | Status is always paired with a text label |
| Elevation | `--df-shadow-sm`, `--df-shadow-md`, `--df-shadow-lg` | Only floating panels use shadows |
| Type | `--df-text-*`, `--df-type-page-title-*`, `--df-type-section-*`, `--df-type-label-*`, `--df-type-meta-*`, `--df-font-weight-*` | Page title 24/650; section 16/600; control 14/550; body 13/400; metadata 12/400 |
| Space and shape | `--df-space-1`…`--df-space-12`, `--df-radius-sm`…`--df-radius-full` | 4-point scale |
| Dimensions | `--df-control-height-*`, `--df-grid-row-height`, `--df-grid-header-height`, `--df-header-height`, `--df-sidebar-width`, `--df-shell-*` | Shell values follow the Figma sheet (header 60, sidebar 208, rail 64) |
| Layers | `--df-z-*` | Sticky, header, sidebar, backdrop, dropdown, modal |
| Motion | `--df-motion-duration-*`, `--df-motion-ease-standard`, `--df-transition-*` | Reduced motion sets durations to 0 in `theme.css` |

## Rules

- Radius: controls 6px; cards 8px; dialogs 12px; pills full.
- Focus: 2px outline in `--df-primary` with a 2px offset. Never remove focus without a replacement.
- Touch: targets at least 44px on coarse pointers.
- Colour is never the only signal for status.

## Migration status

- New components (`components/ui`, `components/shell`) use only tokens and are covered by tests.
- Legacy stylesheets still hold about 2,650 literal colour values across 36 files, and their own tokens. Each module is migrated to tokens and its old stylesheet is deleted when its replacement is verified. Module status is in `migration-tracker.md`.
- Tone tokens (`--df-tone-*`) are a transitional bridge for the legacy stylesheets. They are removed when the modules that use them are migrated.
