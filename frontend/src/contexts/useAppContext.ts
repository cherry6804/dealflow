import { useContext } from "react";

import { AppContext } from "./appContextDefinition";

export function useAppContext() {
  const context = useContext(AppContext);

  if (!context) {
    throw new Error("useAppContext must be used inside an AppProvider.");
  }

  return context;
}