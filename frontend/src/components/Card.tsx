import type { ReactNode } from "react";

export function Card({
  title,
  description,
  actions,
  children,
  className = "",
  as: Tag = "section",
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
}) {
  return (
    <Tag className={`card ${className}`.trim()}>
      {(title || actions || description) && (
        <header className="card-head">
          <div className="card-head-text">
            {title && <h2 className="card-title">{title}</h2>}
            {description && <p className="card-desc">{description}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className="card-body">{children}</div>
    </Tag>
  );
}

export function CardGrid({
  children,
  columns = 2,
}: {
  children: ReactNode;
  columns?: 1 | 2 | 3 | 4;
}) {
  return <div className={`card-grid cols-${columns}`}>{children}</div>;
}
