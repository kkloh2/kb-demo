import { useCallback, useEffect, useState } from "react";
import { AREAS, CATEGORIES, type AuditFilters, type AuditPage } from "../../api/audit";
import { ApiError } from "../../api/http";
import { ChevronIcon, SearchIcon } from "../../components/Icons";
import { MessageBar } from "../../components/MessageBar";
import { Pager } from "../../components/Pager";
import { AuditTable } from "./AuditTable";
import "../../styles/approvals.css";

interface Props {
  /** Fetches one page (the Audit page: everything; a repository: its activity). */
  fetchPage: (filters: AuditFilters) => Promise<AuditPage>;
  /** The Area filter and the Where column: on for the whole trail, off inside one repository. */
  everywhere?: boolean;
  onSessionEnded: (message: string) => void;
}

/** The audit trail as on the Audit page: search and filters, the table, and pages fetched from the server. */
export function AuditTrail({ fetchPage, everywhere = false, onSessionEnded }: Props) {
  const [area, setArea] = useState("");
  const [category, setCategory] = useState("");
  const [actor, setActor] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [data, setData] = useState<AuditPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Back to page 1 whenever the filters or page size change.
  useEffect(() => setPage(1), [area, category, actor, pageSize]);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await fetchPage({ source_system: area, category, actor: actor.trim(),
        offset: (page - 1) * pageSize, limit: pageSize }));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
      else setError(e instanceof Error ? e.message : "Couldn't load the audit trail.");
    }
  }, [fetchPage, area, category, actor, page, pageSize, onSessionEnded]);

  useEffect(() => {
    const t = setTimeout(load, actor ? 300 : 0); // wait for typing to pause
    return () => clearTimeout(t);
  }, [load, actor]);

  const filtered = !!(area || category || actor.trim());

  return (
    <>
      {error && <MessageBar className="alert" role="alert" onClose={() => setError(null)}>{error}</MessageBar>}

      <div className="toolbar">
        <div className="toolbar__left">
          <label className="search">
            <SearchIcon />
            <input type="search" value={actor} onChange={(e) => setActor(e.target.value)}
              placeholder="Search by LAN ID" aria-label="Search by LAN ID" />
          </label>
          {everywhere && (
            <label className="filter">
              <span className="sr-only">Area</span>
              <select value={area} onChange={(e) => setArea(e.target.value)}>
                <option value="">All areas</option>
                {Object.entries(AREAS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <ChevronIcon dir="down" />
            </label>
          )}
          <label className="filter">
            <span className="sr-only">Kind</span>
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All kinds</option>
              {Object.entries(CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <ChevronIcon dir="down" />
          </label>
        </div>
      </div>

      {data === null ? (
        !error && <p className="kb-message">Loading…</p>
      ) : data.total === 0 ? (
        <p className="kb-message">{filtered ? "Nothing matches." : "Nothing has happened here yet."}</p>
      ) : (
        <div className="kb-table-panel">
          <AuditTable events={data.items} showPlace={everywhere} />
          <Pager page={page} pageCount={Math.max(1, Math.ceil(data.total / pageSize))} pageSize={pageSize}
            setPage={setPage} setPageSize={setPageSize} />
        </div>
      )}
    </>
  );
}
