import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { roleName } from "../../api/access";
import { ApiError } from "../../api/http";
import { createHierarchy, createSource, listSources, setGroupRoles, type SourceSystem } from "../../api/sources";
import { EditIcon, PlusIcon, SearchIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { SortHeader, useSort } from "../../components/Sort";
import { Pager, usePagination } from "../../components/Pager";
import { timeAgo } from "../../lib/time";
import type { AdminTabProps } from "../AdminPage";
import { ErrorMessage, Notice, useErrors } from "./common";
import { MessageBar } from "../../components/MessageBar";

/** Platform admins: every source system in a list; Review opens one to see its users and add admins. */
export function SourcesTab({ token, onSessionEnded }: AdminTabProps) {
  const [sources, setSources] = useState<SourceSystem[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [reviewing, setReviewing] = useState<string | null>(null); // source code
  const [reviewMode, setReviewMode] = useState<"list" | "edit" | "add">("list");
  const [notice, setNotice] = useState<string | null>(null);
  const { error, setError, fail } = useErrors(onSessionEnded);

  const load = useCallback(() => {
    listSources(token).then(setSources).catch(fail);
  }, [token, fail]);
  useEffect(load, [load]);

  const { sorted, sort, toggle } = useSort(sources ?? [], {
    name: { value: (s) => s.name },
    created: { value: (s) => s.created_at, desc: true },
    updated: { value: (s) => s.last_updated, desc: true },
  });
  const { rows, ...pager } = usePagination(sorted);
  const open = sources?.find((s) => s.code === reviewing) ?? null;

  return (
    <section className="panel" aria-label="Source systems">
      <div className="panel__head panel__head--end">
        <button type="button" className="btn-primary" onClick={() => setCreating(true)}>
          <PlusIcon />
          Create source system
        </button>
      </div>

      <Notice onClose={() => setNotice(null)}>{notice}</Notice>
      {error && <ErrorMessage onClose={() => setError(null)}>{error}</ErrorMessage>}

      {sources === null ? (
        <p className="admin-message">Loading…</p>
      ) : (
        <>
          <table className="data-table sources-table">
            <colgroup>
              <col />
              <col style={{ width: "160px" }} />
              <col style={{ width: "160px" }} />
              <col style={{ width: "64px" }} />
            </colgroup>
            <thead>
              <tr>
                <SortHeader label="Source system" sortKey="name" sort={sort} onSort={toggle} />
                <SortHeader label="Created" sortKey="created" sort={sort} onSort={toggle} />
                <SortHeader label="Last updated" sortKey="updated" sort={sort} onSort={toggle} />
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.code}>
                  <td>
                    <div className="person">
                      <span className="person__name">{s.name}</span>
                      <span className="person__id">{s.code}</span>
                    </div>
                  </td>
                  <td title={new Date(s.created_at).toLocaleString()}>{timeAgo(s.created_at)}</td>
                  <td title={new Date(s.last_updated).toLocaleString()}>{timeAgo(s.last_updated)}</td>
                  <td className="kb-table__actions">
                    <button type="button" className="kb-icon-btn kb-icon-btn--brand" aria-label={`Edit ${s.name}`}
                      title="Edit" onClick={() => setReviewing(s.code)}>
                      <EditIcon />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager {...pager} />
        </>
      )}

      <Modal open={open !== null} wide
        title={!open ? "" : reviewMode === "edit" ? `Manage user groups - ${open.name}`
          : reviewMode === "add" ? `Add user - ${open.name}` : `Manage users - ${open.name}`}
        onClose={() => setReviewing(null)}>
        {open && (
          <SourceReview
            token={token}
            source={open}
            onModeChange={setReviewMode}
            onCreateHierarchy={() =>
              createHierarchy(token, open.code)
                .then(() => {
                  setNotice(`Created ${open.name}'s hierarchy.`);
                  load();
                })
                .catch(fail)}
            onChanged={(message) => {
              setError(null);
              setNotice(message);
              load();
            }}
            onClose={() => setReviewing(null)}
            onError={fail}
          />
        )}
      </Modal>

      <Modal open={creating} title="Create source system" onClose={() => setCreating(false)}>
        {creating && (
          <SourceForm
            token={token}
            onCancel={() => setCreating(false)}
            onSaved={(message) => {
              setCreating(false);
              setNotice(message);
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>
    </section>
  );
}

/** One source system: everyone in it with their roles, and adding someone to its admins. */
function SourceReview({
  token,
  source: s,
  onModeChange,
  onCreateHierarchy,
  onChanged,
  onClose,
  onError,
}: {
  token: string;
  source: SourceSystem;
  onModeChange: (mode: "list" | "edit" | "add") => void;
  onCreateHierarchy: () => void;
  onChanged: (message: string) => void;
  onClose: () => void;
  onError: (e: unknown) => void;
}) {
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Person | "new" | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const groups = s.hierarchy?.groups ?? [];
  useEffect(() => {
    onModeChange(editing === null ? "list" : editing === "new" ? "add" : "edit");
  }, [editing, onModeChange]);
  useEffect(() => () => onModeChange("list"), [onModeChange]); // closing the window resets the title

  // Everyone in the root's groups, once each: which groups they're in, their roles in each, and when.
  const people = useMemo(() => {
    const byId = new Map<string, Person>();
    for (const g of s.hierarchy?.groups ?? [])
      for (const m of g.members) {
        const p = byId.get(m.lan_id) ?? { lan_id: m.lan_id, display_name: m.display_name, groups: [], added_at: null, updated_at: null };
        p.groups.push({ type: g.type, roles: m.roles });
        if (m.added_at && (!p.added_at || m.added_at < p.added_at)) p.added_at = m.added_at;
        if (m.updated_at && (!p.updated_at || m.updated_at > p.updated_at)) p.updated_at = m.updated_at;
        byId.set(m.lan_id, p);
      }
    return [...byId.values()].sort((a, b) => a.display_name.localeCompare(b.display_name));
  }, [s]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? people.filter((p) => p.lan_id.includes(q)) : people;
  }, [people, query]);
  const { sorted, sort, toggle } = useSort(filtered, {
    name: { value: (p) => p.display_name },
    lan_id: { value: (p) => p.lan_id },
    created: { value: (p) => p.added_at, desc: true },
    updated: { value: (p) => p.updated_at, desc: true },
  });
  const { rows, ...pager } = usePagination(sorted);

  if (editing) {
    return (
      <MemberGroupsForm
        token={token}
        source={s}
        person={editing === "new" ? null : editing}
        onCancel={() => setEditing(null)}
        onSaved={(text) => {
          setEditing(null);
          setMessage({ ok: true, text });
          onChanged(text);
        }}
        onError={onError}
      />
    );
  }

  return (
    <>
      <div className="modal__body">
        {message && (
          <MessageBar className={message.ok ? "notice" : "alert"} onClose={() => setMessage(null)}>
            {message.text}
          </MessageBar>
        )}
        {!s.hierarchy ? (
          <p className="admin-message">No hierarchy yet, so nobody is in it.</p>
        ) : (
          <>
            <div className="toolbar">
              <div className="toolbar__left">
                <label className="search">
                  <SearchIcon />
                  <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search by LAN ID" aria-label="Search by LAN ID" />
                </label>
              </div>
              {groups.length > 0 && (
                <button type="button" className="btn-primary" onClick={() => { setEditing("new"); setMessage(null); }}>
                  <PlusIcon />
                  Add user
                </button>
              )}
            </div>
            {filtered.length === 0 ? (
              <p className="admin-message">{query ? `No one matches “${query}”.` : "Nobody yet."}</p>
            ) : (
              <>
                <table className="data-table members-table">
                  <colgroup>
                    <col />
                    <col style={{ width: "120px" }} />
                    <col style={{ width: "112px" }} />
                    <col style={{ width: "150px" }} />
                    <col style={{ width: "100px" }} />
                    <col style={{ width: "120px" }} />
                    <col style={{ width: "48px" }} />
                  </colgroup>
                  <thead>
                    <tr>
                      <SortHeader label="Name" sortKey="name" sort={sort} onSort={toggle} />
                      <SortHeader label="LAN ID" sortKey="lan_id" sort={sort} onSort={toggle} />
                      <th scope="col">User groups</th>
                      <th scope="col">User group roles</th>
                      <SortHeader label="Created" sortKey="created" sort={sort} onSort={toggle} />
                      <SortHeader label="Last updated" sortKey="updated" sort={sort} onSort={toggle} />
                      <th scope="col">
                        <span className="visually-hidden">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((p) => (
                      <tr key={p.lan_id}>
                        <td className="truncate">{p.display_name}</td>
                        <td className="muted truncate">{p.lan_id}</td>
                        <td>
                          <div className="stack">
                            {p.groups.map((g) => (
                              <span key={g.type} className={groupBadge(g.type)}>{GROUP_LABEL[g.type] ?? g.type}</span>
                            ))}
                          </div>
                        </td>
                        <td>
                          <div className="stack">
                            {p.groups.map((g) => (
                              <span key={g.type} className={groupBadge(g.type)}>
                                {GROUP_LABEL[g.type] ?? g.type} - {g.roles.map(roleName).join(", ")}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td title={p.added_at ? new Date(p.added_at).toLocaleString() : undefined}>
                          {p.added_at ? timeAgo(p.added_at) : "—"}
                        </td>
                        <td title={p.updated_at ? new Date(p.updated_at).toLocaleString() : undefined}>
                          {p.updated_at ? timeAgo(p.updated_at) : "—"}
                        </td>
                        <td className="kb-table__actions">
                          <button type="button" className="kb-icon-btn kb-icon-btn--brand" aria-label={`Edit ${p.display_name}`}
                            title="Edit" onClick={() => { setEditing(p); setMessage(null); }}>
                            <EditIcon />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <Pager {...pager} />
              </>
            )}
          </>
        )}
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onClose}>
          Close
        </button>
        {!s.hierarchy && (
          <button type="button" className="btn-primary" onClick={onCreateHierarchy}>
            Create hierarchy
          </button>
        )}
      </div>
    </>
  );
}

interface Person {
  lan_id: string;
  display_name: string;
  groups: { type: string; roles: string[] }[];
  added_at: string | null;
  updated_at: string | null;
}

const GROUP_LABEL: Record<string, string> = { ADMINS: "Admins", USERS: "Users" };

/** One colour per group, the same in every column: admins red, users grey. */
const groupBadge = (type: string) => (type === "ADMINS" ? "badge" : "badge badge--neutral");

/** Add someone, or change which of the root's groups they're in and with which roles there. */
function MemberGroupsForm({
  token,
  source: s,
  person,
  onCancel,
  onSaved,
  onError,
}: {
  token: string;
  source: SourceSystem;
  person: Person | null; // null: add someone
  onCancel: () => void;
  onSaved: (message: string) => void;
  onError: (e: unknown) => void;
}) {
  const groups = s.hierarchy?.groups ?? [];
  const current = (type: string) => person?.groups.find((g) => g.type === type)?.roles ?? [];
  const [lanId, setLanId] = useState(person?.lan_id ?? "");
  const [chosen, setChosen] = useState<Record<string, Set<string>>>(() =>
    Object.fromEntries(groups.map((g) => [g.type, new Set(person ? current(g.type) : g.type === "ADMINS" ? g.roles : [])])),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(type: string, role: string) {
    setChosen((c) => {
      const next = new Set(c[type]);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return { ...c, [type]: next };
    });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const id = lanId.trim().toLowerCase();
    if (!id) return;
    setBusy(true);
    setError(null);
    try {
      for (const g of groups) {
        const wanted = g.roles.filter((r) => chosen[g.type]?.has(r));
        const had = current(g.type);
        if (wanted.join() !== [...had].sort().join() || (!person && wanted.length))
          await setGroupRoles(token, s.code, g.type, id, wanted);
      }
      onSaved(person ? `Saved ${person.display_name}'s groups in ${s.name}. They'll sign in again to pick it up.`
                     : `Added ${id} to ${s.name}. They'll sign in again to pick it up.`);
    } catch (err) {
      if (err instanceof ApiError && err.status !== 401) setError(err.message);
      else onError(err);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="modal__body">
        {error && <MessageBar className="alert" role="alert" onClose={() => setError(null)}>{error}</MessageBar>}
        <div className="form-grid">
          {person ? (
            <div className="form-field--wide person-head">
              <span className="person-head__name">{person.display_name}</span>
              <span className="person-head__id">{person.lan_id}</span>
            </div>
          ) : (
            <label className="form-field form-field--wide">
              <span>LAN ID</span>
              <input value={lanId} onChange={(e) => setLanId(e.target.value)} required
                autoFocus />
            </label>
          )}
          <fieldset className="form-field form-field--wide role-group">
            <legend>User groups</legend>
            <div className="perm-grid">
              {groups.map((g) => (
                <div key={g.type} className="perm-grid__row" role="group" aria-label={GROUP_LABEL[g.type] ?? g.name}>
                  <span className="perm-grid__group">{GROUP_LABEL[g.type] ?? g.name}</span>
                  <div className="perm-grid__options">
                    {g.roles.map((r) => (
                      <label key={r} className="perm-grid__option">
                        <input type="checkbox" checked={chosen[g.type]?.has(r) ?? false} onChange={() => toggle(g.type, r)} />
                        {roleName(r)}
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </fieldset>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={busy || !lanId.trim()}>
          {busy ? "Saving…" : person ? "Save" : "Add user"}
        </button>
      </div>
    </form>
  );
}

function SourceForm({
  token,
  onCancel,
  onSaved,
  onSessionEnded,
}: {
  token: string;
  onCancel: () => void;
  onSaved: (message: string) => void;
  onSessionEnded: (message: string) => void;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const created = await createSource(token, code, name);
      await createHierarchy(token, created.code); // root named after the code; levels as Data Hub defines them
      onSaved(`Created ${created.name} (${created.code}).`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onSessionEnded(err.message);
      else setError(err instanceof Error ? err.message : "Couldn't create it.");
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="modal__body">
        {error && (
          <MessageBar className="alert" role="alert" onClose={() => setError(null)}>
            {error}
          </MessageBar>
        )}
        <div className="form-grid">
          <label className="form-field">
            <span>Code</span>
            <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} required autoFocus />
          </label>
          <label className="form-field">
            <span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving || !code.trim() || !name.trim()}>
          {saving ? "Creating…" : "Create"}
        </button>
      </div>
    </form>
  );
}
