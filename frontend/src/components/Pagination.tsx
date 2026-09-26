"use client";

export function Pagination({
  page,
  pages,
  total,
  pageSize,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [20, 50, 100],
}: {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  pageSizeOptions?: number[];
}) {
  const safePages = Math.max(pages, 1);
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <nav className="pagination" aria-label="Pagination">
      <p className="pagination-summary">
        {total === 0 ? "No results" : `${from}–${to} of ${total}`}
      </p>
      <div className="pagination-controls">
        {onPageSizeChange && (
          <label className="pagination-size">
            <span className="sr-only">Rows per page</span>
            <select
              className="control control-sm"
              value={pageSize}
              onChange={(event) => onPageSizeChange(Number(event.target.value))}
            >
              {pageSizeOptions.map((size) => (
                <option key={size} value={size}>
                  {size} / page
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
        >
          <span>Previous</span>
        </button>
        <span className="pagination-page" aria-current="page">
          Page {page} of {safePages}
        </span>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= safePages}
        >
          <span>Next</span>
        </button>
      </div>
    </nav>
  );
}
