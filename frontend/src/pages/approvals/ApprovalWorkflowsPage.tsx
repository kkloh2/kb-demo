import { useCallback, useEffect, useMemo, useState } from "react";
import { roleName } from "../../api/access";
import { ApiError } from "../../api/http";
import {
  createWorkflow,
  getWorkflow,
  listWorkflows,
  publishVersion,
  validateFlow,
  type Flow,
  type Workflow,
  type WorkflowSummary,
} from "../../api/workflows";
import { EditIcon, PlusIcon, SearchIcon } from "../../components/Icons";
import { MessageBar } from "../../components/MessageBar";
import { Modal } from "../../components/Modal";
import { SortHeader, useSort } from "../../components/Sort";
import { Pager, usePagination } from "../../components/Pager";
import { timeAgo } from "../../lib/time";
import "../../styles/knowledge-bases.css";
import "../../styles/admin.css";
import "../../styles/kb-detail.css";
import "../../styles/doc-repos.css";
import "../../styles/approvals.css";

interface Props {
  token: string;
  onSessionEnded: (message: string) => void;
}

/** A starting point for a new workflow: Doc Hub's two steps. */
const TEMPLATE: Flow = {
  code: "DOC_HUB.MY_WORKFLOW",
  name: "My workflow",
  start: "maker_upload",
  steps: [
    {
      id: "maker_upload", type: "DOCUMENT_UPLOAD", name: "Raised by a maker",
      role: { user_group: "default", role: "MAKER" },
      on: { PASSED: "checker_review", FAILED: "END:UNAUTHORIZED" },
    },
    {
      id: "checker_review", type: "DOCUMENT_REVIEW", name: "Checker review",
      role: { user_group: "default", role: "CHECKER" }, completion: { rule: "ANY" },
      on: { APPROVED: "END:APPROVED", REJECTED: "END:REJECTED", CHANGES_REQUESTED: "maker_upload" },
    },
  ],
};

/** Platform admins: the workflows approvals run, their versions, and making or publishing one. */
export function ApprovalWorkflowsPage({ token, onSessionEnded }: Props) {
  const [items, setItems] = useState<WorkflowSummary[] | null>(null);
  const [open, setOpen] = useState<string | "new" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(() => {
    listWorkflows(token)
      .then(setItems)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
        else setError(e instanceof Error ? e.message : "Couldn't load the workflows.");
      });
  }, [token, onSessionEnded]);
  useEffect(load, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!items || !q) return items ?? [];
    return items.filter((w) =>
      [w.name, w.code, w.kind_label, ...w.steps.map((s) => s.name)].some((v) => v.toLowerCase().includes(q)),
    );
  }, [items, query]);
  const { sorted, sort, toggle } = useSort(filtered, {
    name: { value: (w) => w.name },
    kind: { value: (w) => w.kind_label },
    version: { value: (w) => w.latest_version, desc: true },
    published: { value: (w) => w.last_published_at, desc: true },
  });
  const { rows, ...pager } = usePagination(sorted);

  return (
    <div className="page">
      <h1 className="page__title">Workflows</h1>

      {notice && <MessageBar onClose={() => setNotice(null)}>{notice}</MessageBar>}
      {error && <MessageBar className="alert" role="alert" onClose={() => setError(null)}>{error}</MessageBar>}

      <div className="toolbar">
        <div className="toolbar__left">
          <label className="search">
            <SearchIcon />
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="Search workflows" aria-label="Search workflows" />
          </label>
        </div>
        <button type="button" className="btn-primary" onClick={() => { setOpen("new"); setNotice(null); }}>
          <PlusIcon />
          New workflow
        </button>
      </div>

      {items === null && !error ? (
        <p className="kb-message">Loading workflows…</p>
      ) : filtered.length === 0 ? (
        <p className="kb-message">{query ? `No workflows match “${query}”.` : "No workflows yet."}</p>
      ) : items ? (
        <div className="kb-table-panel">
          <table className="data-table members-table">
            <colgroup>
              <col />
              <col style={{ width: "120px" }} />
              <col style={{ width: "32%" }} />
              <col style={{ width: "90px" }} />
              <col style={{ width: "140px" }} />
              <col style={{ width: "48px" }} />
            </colgroup>
            <thead>
              <tr>
                <SortHeader label="Workflow" sortKey="name" sort={sort} onSort={toggle} />
                <SortHeader label="For" sortKey="kind" sort={sort} onSort={toggle} />
                <th scope="col">Steps</th>
                <SortHeader label="Version" sortKey="version" sort={sort} onSort={toggle} />
                <SortHeader label="Last published" sortKey="published" sort={sort} onSort={toggle} />
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((w) => (
                <tr key={w.id}>
                  <td>
                    <div className="person" title={`${w.name} (${w.code})`}>
                      <span className="person__name truncate">{w.name}</span>
                      <span className="person__id truncate">{w.code}</span>
                    </div>
                  </td>
                  <td>
                    <span className="kb-badge kb-badge--cell">{w.kind_label}</span>
                  </td>
                  <td className="cell-wrap">
                    {w.steps.map((s) => s.name).join(" → ")}
                  </td>
                  <td>v{w.latest_version}</td>
                  <td title={w.last_published_at ? new Date(w.last_published_at).toLocaleString() : undefined}>
                    {w.last_published_at ? timeAgo(w.last_published_at) : "—"}
                  </td>
                  <td className="kb-table__actions">
                    <button type="button" className="kb-icon-btn kb-icon-btn--brand" aria-label={`Edit ${w.name}`}
                      title="Edit" onClick={() => { setOpen(w.id); setNotice(null); }}>
                      <EditIcon />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager {...pager} />
        </div>
      ) : null}

      <Modal open={open !== null} title={open === "new" ? "New workflow" : "Edit workflow"}
        onClose={() => setOpen(null)} wide>
        {open && (
          <WorkflowEditor
            key={open}
            token={token}
            workflowId={open === "new" ? null : open}
            onClose={() => setOpen(null)}
            onSaved={(text) => {
              setOpen(null);
              setNotice(text);
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>
    </div>
  );
}

function target(t: string, flow: Flow): string {
  if (t.startsWith("END:")) return `ends: ${t.slice(4).replace(/_/g, " ").toLowerCase()}`;
  return flow.steps.find((s) => s.id === t)?.name ?? t;
}

/** The steps of a flow, readable. */
export function FlowSteps({ flow }: { flow: Flow }) {
  return (
    <ol className="flow-steps">
      {flow.steps.map((s, i) => (
        <li key={s.id} className="flow-step">
          <span className="flow-step__num">{i + 1}</span>
          <div className="flow-step__body">
            <div className="flow-step__head">
              <strong>{s.name}</strong>
              <span className="badge badge--neutral">{s.type}</span>
              {flow.start === s.id && <span className="badge">Start</span>}
            </div>
            {s.role && (
              <p className="muted">
                {roleName(s.role.role)} in the user group “{s.role.user_group}”
              </p>
            )}
            <p className="flow-step__on">
              {Object.entries(s.on).map(([outcome, t]) => (
                <span key={outcome}>
                  {outcome.replace(/_/g, " ").toLowerCase()} → {target(t, flow)}
                </span>
              ))}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** One workflow (or a new one): its steps, the JSON to edit, Check and Publish/Create, its versions. */
function WorkflowEditor({
  token,
  workflowId,
  onClose,
  onSaved,
  onSessionEnded,
}: {
  token: string;
  workflowId: string | null; // null: a new workflow
  onClose: () => void;
  onSaved: (message: string) => void;
  onSessionEnded: (message: string) => void;
}) {
  const [wf, setWf] = useState<Workflow | null>(null);
  const [text, setText] = useState(workflowId ? "" : JSON.stringify(TEMPLATE, null, 2));
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [busy, setBusy] = useState<"check" | "save" | null>(null);

  function fail(e: unknown) {
    if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
    else setResult({ ok: false, message: e instanceof Error ? e.message : "Something went wrong." });
  }

  useEffect(() => {
    if (!workflowId) return;
    getWorkflow(token, workflowId)
      .then((w) => {
        setWf(w);
        setText(JSON.stringify(w.versions[0]?.definition ?? {}, null, 2));
      })
      .catch(fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, workflowId]);

  function parsed(): unknown | null {
    try {
      return JSON.parse(text);
    } catch (e) {
      setResult({ ok: false, message: `That isn't valid JSON: ${e instanceof Error ? e.message : ""}` });
      return null;
    }
  }

  async function check() {
    const definition = parsed();
    if (definition === null) return;
    setBusy("check");
    setResult(null);
    try {
      const r = await validateFlow(token, definition);
      setResult({ ok: true, message: `The workflow is valid: ${r.steps} steps, starting at ${r.start}.` });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    const definition = parsed();
    if (definition === null) return;
    setBusy("save");
    setResult(null);
    try {
      if (wf) {
        const v = await publishVersion(token, wf.id, definition);
        onSaved(`Published ${wf.name} version ${v.version}. New requests use it; running ones keep theirs.`);
      } else {
        const created = await createWorkflow(token, definition);
        onSaved(`Created ${created.name}. Repositories can now choose it.`);
      }
    } catch (e) {
      fail(e);
      setBusy(null);
    }
  }

  if (workflowId && !wf) {
    return (
      <div className="modal__body">
        {result ? <MessageBar className="alert" role="alert">{result.message}</MessageBar> : <p className="muted">Loading…</p>}
      </div>
    );
  }
  const current = wf?.versions[0]?.definition;

  return (
    <>
      <div className="modal__body workflow-editor">
        {wf && (
          <div className="person-head">
            <span className="person-head__name">{wf.name}</span>
            <span className="person-head__id">
              {wf.code} · v{wf.latest_version} · {wf.kind_label} ·{" "}
              {wf.used_by_nodes.length ? `used by ${wf.used_by_nodes.join(", ")}` : "not used yet"}
            </span>
          </div>
        )}

        {current && (
          <section className="meta-section">
            <h4 className="meta-section__title">Steps (version {wf?.latest_version})</h4>
            <FlowSteps flow={current} />
          </section>
        )}

        <section className="meta-section">
          <h4 className="meta-section__title">Workflow (JSON)</h4>
          {result && (
            <MessageBar className={result.ok ? "notice" : "alert"} role={result.ok ? undefined : "alert"}
              onClose={() => setResult(null)}>
              {result.message}
            </MessageBar>
          )}
          <textarea className="flow-json" value={text} spellCheck={false} aria-label="Workflow JSON"
            onChange={(e) => { setText(e.target.value); setResult(null); }} />
        </section>

        {wf && (
          <section className="meta-section">
            <h4 className="meta-section__title">Versions</h4>
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Version</th>
                  <th scope="col">Published</th>
                  <th scope="col">Steps</th>
                </tr>
              </thead>
              <tbody>
                {wf.versions.map((v) => (
                  <tr key={v.id}>
                    <td>v{v.version}</td>
                    <td>{v.published_at ? new Date(v.published_at).toLocaleString() : "—"}</td>
                    <td className="truncate">{v.definition.steps.map((s) => s.name).join(" → ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onClose}>
          Close
        </button>
        <button type="button" className="btn-outline" disabled={busy !== null} onClick={check}>
          {busy === "check" ? "Checking…" : "Check"}
        </button>
        <button type="button" className="btn-primary" disabled={busy !== null} onClick={save}>
          {busy === "save" ? "Saving…" : wf ? `Publish as version ${wf.latest_version + 1}` : "Create workflow"}
        </button>
      </div>
    </>
  );
}
