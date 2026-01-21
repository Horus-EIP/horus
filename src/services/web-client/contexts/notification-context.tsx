'use client';

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  ReactNode,
} from "react";

type NotificationVariant = "success" | "error" | "warning" | "info";

export interface Notification {
  id: string;
  message: string;
  variant: NotificationVariant;
}

interface NotificationContextValue {
  notify: (message: string, variant?: NotificationVariant) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  warning: (message: string) => void;
  info: (message: string) => void;
}

const NotificationContext = createContext<NotificationContextValue | undefined>(
  undefined
);

const AUTO_DISMISS_MS = 4000;

export const NotificationProvider = ({ children }: { children: ReactNode }) => {
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const removeNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const createNotification = useCallback(
    (message: string, variant: NotificationVariant = "info") => {
      const id =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random()}`;

      const notification: Notification = { id, message, variant };

      setNotifications((prev) => {
        const isDuplicate = prev.some(
          (n) => n.message === message && n.variant === variant
        );

        if (isDuplicate) {
          return prev;
        }

        return [...prev, notification];
      });

      setTimeout(() => removeNotification(id), AUTO_DISMISS_MS);
    },
    [removeNotification]
  );

  const value: NotificationContextValue = {
    notify: createNotification,
    success: (message) => createNotification(message, "success"),
    error: (message) => createNotification(message, "error"),
    warning: (message) => createNotification(message, "warning"),
    info: (message) => createNotification(message, "info"),
  };

  return (
    <NotificationContext.Provider value={value}>
      {children}

      <div className="pointer-events-none fixed inset-x-0 top-4 z-50 flex flex-col items-center gap-2">
        {notifications.map((n) => (
          <div
            key={n.id}
            className={`
              pointer-events-auto rounded-md px-4 py-3 shadow-lg text-sm text-white
              ${n.variant === "success" ? "bg-green-600" : ""}
              ${n.variant === "error" ? "bg-red-600" : ""}
              ${n.variant === "warning" ? "bg-yellow-500" : ""}
              ${n.variant === "info" ? "bg-blue-600" : ""}
            `}
          >
            {n.message}
          </div>
        ))}
      </div>
    </NotificationContext.Provider>
  );
};

export const useNotification = (): NotificationContextValue => {
  const ctx = useContext(NotificationContext);
  if (!ctx) {
    throw new Error(
      "useNotification must be used within a NotificationProvider"
    );
  }
  return ctx;
};
