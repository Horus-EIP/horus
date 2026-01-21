'use client';

import React from "react";
import { useNotification } from "@/contexts/notification-context";

type ErrorBoundaryProps = {
  children: React.ReactNode;
  fallback?: React.ReactNode;
};

type ErrorBoundaryState = { hasError: boolean };

type InnerProps = ErrorBoundaryProps & {
  onError?: (error: unknown, info: unknown) => void;
};

class ErrorBoundaryInner extends React.Component<InnerProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, errorInfo: unknown) {
    console.error("React error boundary caught:", error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback || (
          <div className="p-4 rounded bg-red-100 text-red-800 space-y-2">
            <p>Something went wrong. Please try again.</p>
          </div>
        )
      );
    }
    return this.props.children;
  }
}

export function ErrorBoundary(props: ErrorBoundaryProps) {
  const { error: notifyError } = useNotification();

  return (
    <ErrorBoundaryInner
      {...props}
      onError={() =>
        notifyError("An unexpected error occurred. Please reload the page.")
      }
    />
  );
}
