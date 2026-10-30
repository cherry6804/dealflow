
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";
import "./styles/layouts.css";
import "./styles/auth.css";
import "./styles/workspace-customizer.css";

import App from "./App";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("DealFlow could not find the root application element.");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
