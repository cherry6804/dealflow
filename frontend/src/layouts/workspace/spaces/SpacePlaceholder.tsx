import { Link } from "react-router-dom";

import type { SpaceDefinition, SpaceTab } from "./spaceConfig";
import { firstRoutableTab } from "./spaceNavigation";

/**
 * Shown for a tab that has no route yet. It states that the area is not available; it does not show sample data.
 */
export function SpacePlaceholder({ space, tab }: { space: SpaceDefinition; tab: SpaceTab }) {
  return (
    <section className="df-state df-state--placeholder" aria-labelledby="df-placeholder-title">
      <h2 id="df-placeholder-title" className="df-state-title">
        {tab.label} is not available yet
      </h2>
      <p className="df-state-message">
        This part of {space.label} is part of a later release. No data is shown here.
      </p>
      {firstRoutableTab(space) ? (
        <Link className="df-space-tab" to={firstRoutableTab(space)?.to ?? "/"}>
          Open an available {space.label.toLowerCase()} tab
        </Link>
      ) : null}
    </section>
  );
}
