import React from "react";
import { createRoot } from "react-dom/client";

import App from "./App.jsx";
import { FrontendErrorBoundary, initFrontendMonitoring } from "./monitoring.tsx";
import "./styles.css";

initFrontendMonitoring();

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <FrontendErrorBoundary>
      <App />
    </FrontendErrorBoundary>
  </React.StrictMode>,
);
