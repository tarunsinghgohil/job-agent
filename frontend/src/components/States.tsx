import type { ReactNode } from "react";

export function LoadingState({ label = "Loading…", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div className="state state-loading" role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div className="skeletons" aria-hidden="true">
        {Array.from({ length: rows }).map((_, index) => (
          <div key={index} className="skeleton" />
        ))}
      </div>
      <p className="state-text">{label}</p>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon = "∅",
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="state state-empty">
      <div className="state-icon" aria-hidden="true">
        {icon}
      </div>
      <h3 className="state-title">{title}</h3>
      {description && <p className="state-text">{description}</p>}
      {action && <div className="state-action">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state state-error" role="alert">
      <div className="state-icon" aria-hidden="true">
        !
      </div>
      <h3 className="state-title">{title}</h3>
      <p className="state-text">{message}</p>
      {onRetry && (
        <div className="state-action">
          <button type="button" className="btn btn-secondary btn-md" onClick={onRetry}>
            <span>Try again</span>
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Renders the right state for a resource in one place, so no page forgets the
 * loading / error / empty branches.
 */
export function AsyncBoundary<T>({
  loading,
  error,
  data,
  onRetry,
  empty,
  isEmpty,
  children,
  loadingLabel,
}: {
  loading: boolean;
  error: string | null;
  data: T | null;
  onRetry?: () => void;
  empty?: ReactNode;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => ReactNode;
  loadingLabel?: string;
}) {
  if (loading && data === null) return <LoadingState label={loadingLabel} />;
  if (error && data === null) return <ErrorState message={error} onRetry={onRetry} />;
  if (data === null) return <>{empty ?? <EmptyState title="No data available" />}</>;
  if (isEmpty && isEmpty(data)) return <>{empty ?? <EmptyState title="Nothing here yet" />}</>;
  return (
    <>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {children(data)}
    </>
  );
}
