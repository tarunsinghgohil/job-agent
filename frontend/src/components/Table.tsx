"use client";

import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  /** Sort key sent to the API; omit to make the column unsortable. */
  sortKey?: string;
  align?: "left" | "right" | "center";
  width?: string;
}

export interface TableProps<T> {
  columns: Array<Column<T>>;
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  sort?: string;
  onSortChange?: (sort: string) => void;
  caption?: string;
}

/**
 * Sort values are `field` / `-field`, matching the `sort` query parameter in
 * the API contract.
 */
export function Table<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  sort,
  onSortChange,
  caption,
}: TableProps<T>) {
  const currentField = sort?.startsWith("-") ? sort.slice(1) : sort;
  const descending = Boolean(sort?.startsWith("-"));

  function toggleSort(key: string) {
    if (!onSortChange) return;
    onSortChange(currentField === key && !descending ? `-${key}` : key);
  }

  return (
    <div className="table-wrap">
      <table className="table">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((column) => {
              const sortable = Boolean(column.sortKey && onSortChange);
              const isSorted = column.sortKey && currentField === column.sortKey;
              return (
                <th
                  key={column.key}
                  scope="col"
                  style={column.width ? { width: column.width } : undefined}
                  className={`align-${column.align ?? "left"}`}
                  aria-sort={
                    isSorted ? (descending ? "descending" : "ascending") : sortable ? "none" : undefined
                  }
                >
                  {sortable ? (
                    <button
                      type="button"
                      className="th-sort"
                      onClick={() => toggleSort(column.sortKey as string)}
                    >
                      {column.header}
                      <span aria-hidden="true" className="th-sort-arrow">
                        {isSorted ? (descending ? "▼" : "▲") : "↕"}
                      </span>
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              className={onRowClick ? "row-clickable" : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              role={onRowClick ? "link" : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={
                onRowClick
                  ? (event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onRowClick(row);
                      }
                    }
                  : undefined
              }
            >
              {columns.map((column) => (
                <td key={column.key} className={`align-${column.align ?? "left"}`}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
