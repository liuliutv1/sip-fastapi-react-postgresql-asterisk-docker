import * as Sentry from "@sentry/react";
import type { PropsWithChildren } from "react";

const dsn = import.meta.env.VITE_SENTRY_DSN || "";
const environment = import.meta.env.VITE_SENTRY_ENVIRONMENT || "production";
const release = import.meta.env.VITE_APP_VERSION || "unknown";

export function initFrontendMonitoring() {
  if (!dsn) {
    return;
  }
  Sentry.init({
    dsn,
    environment,
    release,
    tracesSampleRate: 0.05,
  });
}

export function captureFrontendError(error: unknown, context?: Record<string, unknown>) {
  if (!dsn) {
    return;
  }
  Sentry.withScope((scope) => {
    if (context) {
      scope.setContext("sipcc", context);
    }
    Sentry.captureException(error);
  });
}

export function FrontendErrorBoundary({ children }: PropsWithChildren) {
  if (!dsn) {
    return <>{children}</>;
  }
  return (
    <Sentry.ErrorBoundary fallback={<main className="app-shell"><div className="error-banner">页面发生错误，已上报监控，请刷新后重试。</div></main>}>
      {children}
    </Sentry.ErrorBoundary>
  );
}
