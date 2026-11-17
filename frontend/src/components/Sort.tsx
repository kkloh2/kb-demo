import { useMemo, useRef, useState } from "react";
import { SortIcon } from "./Icons";

export type SortDir = "asc" | "desc";
export type SortState<K extends string> = { key: K; dir: SortDir } | null;
type Value = string | number | boolean | null | undefined;

/** A sortable column: how to read its value, and whether it starts newest/largest first. */
export type SortColumn<T> = { value: (item: T) => Value; desc?: boolean };

function compare(a: Value, b: Value): number {
  const empty = (v: Value) => v === null || v === undefined || v === "";
  if (empty(a) || empty(b)) return empty(a) === empty(b) ? 0 : empty(a) ? 1 : -1; // blanks last
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { sensitivity: "base", numeric: true });
}

/**
 * Client-side sorting for a table, as on the repositories list. `initial` null keeps the items'
 * own order until a header is clicked. Clicking a header sorts by it (dates newest first, the rest
 * A–Z); clicking it again reverses. Blanks always go last.
 */
export function useSort<T, K extends string>(items: T[], columns: Record<K, SortColumn<T>>, initial: SortState<NoInfer<K>> = null) {
  const [sort, setSort] = useState<SortState<K>>(initial);
  const cols = useRef(columns);
  cols.current = columns;

  const sorted = useMemo(() => {
    if (!sort) return items;
    const read = cols.current[sort.key].value;
    const out = [...items].sort((a, b) => compare(read(a), read(b)));
    return sort.dir === "asc" ? out : out.reverse();
  }, [items, sort]);

  function toggle(key: K) {
    setSort((s) =>
      s?.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: cols.current[key].desc ? "desc" : "asc" },
    );
  }

  return { sorted, sort, toggle };
}

interface HeaderProps<K extends string> {
  label: string;
  sortKey?: K; // left out: a plain header
  sort: SortState<K>;
  onSort: (key: K) => void;
  className?: string;
}

/** A table header with the sort button (the repositories list's look), or a plain one. */
export function SortHeader<K extends string>({ label, sortKey, sort, onSort, className }: HeaderProps<K>) {
  const active = sortKey !== undefined && sort?.key === sortKey;
  return (
    <th scope="col" className={className}
      aria-sort={sortKey ? (active ? (sort!.dir === "asc" ? "ascending" : "descending") : "none") : undefined}>
      <div className="kb-table__th">
        <span className="kb-table__th-label" title={label}>
          {label}
        </span>
        {sortKey && (
          <button type="button" className="kb-table__sort" aria-label={`Sort by ${label}`} title={`Sort by ${label}`}
            onClick={() => onSort(sortKey)}>
            <SortIcon dir={active ? sort!.dir : "none"} />
          </button>
        )}
      </div>
    </th>
  );
}
