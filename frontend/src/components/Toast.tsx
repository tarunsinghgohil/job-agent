"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { errorMessage } from "../lib/api";

export type ToastTone = "success" | "error" | "info";

interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastContextValue {
  push: (message: string, tone?: ToastTone) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
  /** Runs an action, toasting success or the serialized ApiError message. */
  withToast: <T>(
    action: () => Promise<T>,
    successMessage: string,
    failureMessage?: string,
  ) => Promise<T | undefined>;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const AUTO_DISMISS_MS = 5000;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (message: string, tone: ToastTone = "info") => {
      const id = nextId.current++;
      setToasts((current) => [...current, { id, tone, message }]);
      setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  const value = useMemo<ToastContextValue>(() => {
    const success = (message: string) => push(message, "success");
    const error = (message: string) => push(message, "error");
    const info = (message: string) => push(message, "info");
    return {
      push,
      success,
      error,
      info,
      withToast: async <T,>(
        action: () => Promise<T>,
        successMessage: string,
        failureMessage?: string,
      ) => {
        try {
          const result = await action();
          success(successMessage);
          return result;
        } catch (err) {
          error(failureMessage ? `${failureMessage}: ${errorMessage(err)}` : errorMessage(err));
          return undefined;
        }
      },
    };
  }, [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast-${toast.tone}`}>
            <span>{toast.message}</span>
            <button
              type="button"
              className="toast-close"
              aria-label="Dismiss notification"
              onClick={() => dismiss(toast.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>.");
  return context;
}
