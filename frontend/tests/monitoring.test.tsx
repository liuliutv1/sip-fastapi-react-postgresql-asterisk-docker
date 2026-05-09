import { describe, expect, it, vi } from "vitest";

import { captureFrontendError, initFrontendMonitoring } from "../src/monitoring";

describe("frontend monitoring", () => {
  it("is safe when Sentry DSN is not configured", () => {
    expect(() => initFrontendMonitoring()).not.toThrow();
    expect(() => captureFrontendError(new Error("boom"), { path: "/api/test" })).not.toThrow();
  });
});
