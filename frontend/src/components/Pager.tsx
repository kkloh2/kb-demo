import { useEffect, useState } from "react";
import { ChevronIcon, PageEdgeIcon } from "./Icons";

const PAGE_SIZES = [10, 25, 50];

/** Client-side pagination state. Resets to page 1 when the items or page size change. */
export function usePagination<T>(items: T[], initialSize = 25) {
  const [pageSize, setPageSize] = useState(initialSize);
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [items, pageSize]);
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  return {
    rows: items.slice((page - 1) * pageSize, page * pageSize),
    page,
    pageCount,
    pageSize,
    setPage,
    setPageSize,
  };
}

type Props = Omit<ReturnType<typeof usePagination>, "rows">;

/** "Items per page" select plus first / previous / pages / next / last buttons. */
export function Pager({ page, pageCount, pageSize, setPage, setPageSize }: Props) {
  return (
    <div className="pager">
      <label className="pager__size">
        Items per page
        <span className="pager__select">
          <select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <ChevronIcon dir="down" />
        </span>
      </label>
      <nav className="pager__nav" aria-label="Pagination">
        <button type="button" aria-label="First page" disabled={page === 1} onClick={() => setPage(1)}>
          <PageEdgeIcon dir="first" />
        </button>
        <button type="button" aria-label="Previous page" disabled={page === 1} onClick={() => setPage(page - 1)}>
          <ChevronIcon dir="left" />
        </button>
        {Array.from({ length: pageCount }, (_, i) => i + 1).map((n) => (
          <button
            key={n}
            type="button"
            className="pager__page"
            aria-current={n === page ? "page" : undefined}
            aria-label={`Page ${n}`}
            onClick={() => setPage(n)}
          >
            {n}
          </button>
        ))}
        <button type="button" aria-label="Next page" disabled={page === pageCount} onClick={() => setPage(page + 1)}>
          <ChevronIcon dir="right" />
        </button>
        <button type="button" aria-label="Last page" disabled={page === pageCount} onClick={() => setPage(pageCount)}>
          <PageEdgeIcon dir="last" />
        </button>
      </nav>
    </div>
  );
}
