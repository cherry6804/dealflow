import { Navigate, useParams } from "react-router-dom";

import { SPACE_DEFINITIONS } from "./spaceConfig";
import { SpacePlaceholder } from "./SpacePlaceholder";

/** Route for placeholder tabs. Unknown space or tab ids redirect to the Overview dashboard. */
export default function SpacePlaceholderRoute() {
  const { spaceId, tabId } = useParams();
  const space = SPACE_DEFINITIONS.find((candidate) => candidate.id === spaceId);
  const tab = space?.tabs.find((candidate) => candidate.id === tabId);
  if (!space || !tab || !tab.placeholder) return <Navigate to="/" replace />;
  return <SpacePlaceholder space={space} tab={tab} />;
}
