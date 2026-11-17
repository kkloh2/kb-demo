import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { listUsers, roleName, upsertUser, type AdminUser } from "../../api/access";
import { listSources, setGroupRoles, type SourceSystem } from "../../api/sources";
import { ApiError } from "../../api/http";
import { EditIcon, PlusIcon, SearchIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { SortHeader, useSort } from "../../components/Sort";
import { Pager, usePagination } from "../../components/Pager";
import { timeAgo } from "../../lib/time";
import type { AdminTabProps } from "../AdminPage";
import { ErrorMessage, Notice, useErrors } from "./common";
import { MessageBar } from "../../components/MessageBar";

type Editing = { mode: "add" } | { mode: "edit"; user: AdminUser } | null;

const when = (iso: string | null, never = "—") =>
  iso ? <span title={new Date(iso).toLocaleString()}>{timeAgo(iso)}</span> : <span className="muted">{never}</span>;

/** Everyone who has signed in or been added. Edit sets their user groups and roles in each source system. */
export function UsersTab({ token, user: me, onSessionEnded }: AdminTabProps) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Editing>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { error, setError, fail } = useErrors(onSessionEnded);

  const load = useCallback(() => {
    listUsers(token).then(setUsers).catch(fail);
  }, [token, fail]);
  useEffect(load, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? (users ?? []).filter((u) => u.lan_id.includes(q)) : users ?? [];
  }, [users, query]);
  const { sorted, sort, toggle } = useSort(filtered, {
    name: { value: (u) => u.display_name },
    lan_id: { value: (u) => u.lan_id },
    email: { value: (u) => u.email },
    department: { value: (u) => u.directory_department },
    last_login: { value: (u) => u.last_login_at, desc: true },
    created: { value: (u) => u.created_at, desc: true },
    updated: { value: (u) => u.updated_at, desc: true },
  });
  const { rows, ...pager } = usePagination(sorted);

  return (
    <section className="panel" aria-label="Users">
      <div className="toolbar">
        <div className="toolbar__left">
          <label className="search">
            <SearchIcon />
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by LAN ID" aria-label="Search by LAN ID" />
          </label>
        </div>
        <button type="button" className="btn-primary" onClick={() => setEditing({ mode: "add" })}>
          <PlusIcon />
          Add user
        </button>
      </div>

      <Notice onClose={() => setNotice(null)}>{notice}</Notice>

      {error ? (
        <ErrorMessage onClose={() => setError(null)}>{error}</ErrorMessage>
      ) : users === null ? (
        <p className="admin-message">Loading users…</p>
      ) : filtered.length === 0 ? (
        <p className="admin-message">{query ? `No one matches “${query}”.` : "Nobody yet."}</p>
      ) : (
        <>
          <table className="data-table members-table">
            <colgroup>
              <col />
              <col style={{ width: "120px" }} />
              <col style={{ width: "22%" }} />
              <col style={{ width: "14%" }} />
              <col style={{ width: "110px" }} />
              <col style={{ width: "110px" }} />
              <col style={{ width: "120px" }} />
              <col style={{ width: "48px" }} />
            </colgroup>
            <thead>
              <tr>
                <SortHeader label="Name" sortKey="name" sort={sort} onSort={toggle} />
                <SortHeader label="LAN ID" sortKey="lan_id" sort={sort} onSort={toggle} />
                <SortHeader label="Email" sortKey="email" sort={sort} onSort={toggle} />
                <SortHeader label="Department" sortKey="department" sort={sort} onSort={toggle} />
                <SortHeader label="Last sign-in" sortKey="last_login" sort={sort} onSort={toggle} />
                <SortHeader label="Created" sortKey="created" sort={sort} onSort={toggle} />
                <SortHeader label="Last updated" sortKey="updated" sort={sort} onSort={toggle} />
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.lan_id} className={u.status === "ACTIVE" ? undefined : "row--muted"}
                  title={u.status === "ACTIVE" ? undefined : "Access switched off"}>
                  <td className="truncate">{u.display_name}</td>
                  <td className="muted truncate">{u.lan_id}</td>
                  <td className="truncate">{u.email}</td>
                  <td className="truncate">{u.directory_department || <span className="muted">—</span>}</td>
                  <td>{when(u.last_login_at, "Never")}</td>
                  <td>{when(u.created_at)}</td>
                  <td>{when(u.updated_at)}</td>
                  <td className="kb-table__actions">
                    <button type="button" className="kb-icon-btn kb-icon-btn--brand" aria-label={`Edit ${u.display_name}`}
                      title="Edit" onClick={() => setEditing({ mode: "edit", user: u })}>
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

      <Modal open={editing !== null} title={editing?.mode === "edit" ? "Edit user" : "Add user"}
        onClose={() => setEditing(null)}>
        {editing?.mode === "add" && (
          <AddUserForm
            token={token}
            existing={new Set((users ?? []).map((u) => u.lan_id))}
            onCancel={() => setEditing(null)}
            onSaved={(lanId) => {
              setEditing(null);
              setNotice(`Added ${lanId}. Their name and email fill in from the directory at their first sign-in.`);
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
        {editing?.mode === "edit" && (
          <UserForm
            token={token}
            user={editing.user}
            isMe={editing.user.lan_id === me.username}
            onCancel={() => setEditing(null)}
            onSaved={(message) => {
              setEditing(null);
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

/**
 * Add someone by LAN ID and choose their user groups and roles in each source system (the same
 * layout as Source systems -> Add user). Only Platform -> Users (Viewer) starts ticked; anything
 * left unticked, including other systems' users groups they'd otherwise join, they don't get.
 */
function AddUserForm({
  token,
  existing,
  onCancel,
  onSaved,
  onSessionEnded,
}: {
  token: string;
  existing: Set<string>; // LAN IDs already here
  onCancel: () => void;
  onSaved: (lanId: string) => void;
  onSessionEnded: (message: string) => void;
}) {
  const [sources, setSources] = useState<SourceSystem[] | null>(null);
  const [lanId, setLanId] = useState("");
  const [chosen, setChosen] = useState<Record<string, Set<string>>>({}); // "SYSTEM:GROUP" -> roles
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    listSources(token)
      .then((s) => {
        const ready = s.filter((x) => x.hierarchy);
        setSources(ready);
        setChosen(Object.fromEntries(ready.flatMap((x) => x.hierarchy!.groups.map((g) =>
          [`${x.code}:${g.type}`, new Set(x.code === "PLATFORM" && g.type === "USERS" ? g.roles : [])]))));
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
        else setError(e instanceof Error ? e.message : "Couldn't load the source systems.");
      });
  }, [token, onSessionEnded]);

  function toggle(key: string, role: string) {
    setChosen((c) => {
      const next = new Set(c[key]);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return { ...c, [key]: next };
    });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const id = lanId.trim().toLowerCase();
    if (!id || !sources) return;
    if (existing.has(id)) {
      setError(`${id} is already here. Use Edit on their row.`);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await upsertUser(token, id, {});
      // A new user has just joined every users group (auto-join); change only what differs.
      for (const s of sources)
        for (const g of s.hierarchy!.groups) {
          const wanted = g.roles.filter((r) => chosen[`${s.code}:${g.type}`]?.has(r));
          const now = g.auto_join_role ? [g.auto_join_role] : [];
          if (wanted.join() !== now.join()) await setGroupRoles(token, s.code, g.type, id, wanted);
        }
      onSaved(id);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onSessionEnded(err.message);
      else setError(err instanceof Error ? err.message : "Couldn't add them.");
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
          <label className="form-field form-field--wide">
            <span>LAN ID</span>
            <input value={lanId} onChange={(e) => setLanId(e.target.value)} required autoFocus />
          </label>
          <fieldset className="form-field form-field--wide role-group">
            <legend>User groups</legend>
            {sources === null ? (
              <small>Loading…</small>
            ) : (
              <div className="perm-grid">
                {sources.map((s) => (
                  <div key={s.code} className="perm-grid__row" role="group" aria-label={s.name}>
                    <span className="perm-grid__group">{s.name}</span>
                    <div className="perm-grid__options">
                      {s.hierarchy!.groups.flatMap((g) =>
                        g.roles.map((r) => {
                          const key = `${s.code}:${g.type}`;
                          return (
                            <label key={`${key}:${r}`} className="perm-grid__option">
                              <input type="checkbox" checked={chosen[key]?.has(r) ?? false} onChange={() => toggle(key, r)} />
                              {GROUP_LABEL[g.type] ?? g.name} - {roleName(r)}
                            </label>
                          );
                        }),
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </fieldset>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving || !lanId.trim() || sources === null}>
          {saving ? "Adding…" : "Add user"}
        </button>
      </div>
    </form>
  );
}

const GROUP_LABEL: Record<string, string> = { ADMINS: "Admins", USERS: "Users" };

/**
 * Edit someone the same way as Add user (and Source systems -> Manage users): their user groups
 * and roles in every source system. Their name, email,
 * title and department come from the directory.
 */
function UserForm({
  token,
  user: u,
  isMe,
  onCancel,
  onSaved,
  onSessionEnded,
}: {
  token: string;
  user: AdminUser;
  isMe: boolean;
  onCancel: () => void;
  onSaved: (message: string) => void;
  onSessionEnded: (message: string) => void;
}) {
  const [sources, setSources] = useState<SourceSystem[] | null>(null);
  const [current, setCurrent] = useState<Record<string, string[]>>({}); // "SYSTEM:GROUP" -> roles now
  const [chosen, setChosen] = useState<Record<string, Set<string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    listSources(token)
      .then((s) => {
        const ready = s.filter((x) => x.hierarchy);
        const now: Record<string, string[]> = {};
        for (const x of ready)
          for (const g of x.hierarchy!.groups)
            now[`${x.code}:${g.type}`] = g.members.find((m) => m.lan_id === u.lan_id)?.roles ?? [];
        setSources(ready);
        setCurrent(now);
        setChosen(Object.fromEntries(Object.entries(now).map(([k, roles]) => [k, new Set(roles)])));
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
        else setError(e instanceof Error ? e.message : "Couldn't load the source systems.");
      });
  }, [token, u.lan_id, onSessionEnded]);

  function toggle(key: string, role: string) {
    setChosen((c) => {
      const next = new Set(c[key]);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return { ...c, [key]: next };
    });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!sources) return;
    setSaving(true);
    setError(null);
    try {
      for (const s of sources)
        for (const g of s.hierarchy!.groups) {
          const key = `${s.code}:${g.type}`;
          const wanted = g.roles.filter((r) => chosen[key]?.has(r));
          if (wanted.join() !== [...(current[key] ?? [])].sort().join())
            await setGroupRoles(token, s.code, g.type, u.lan_id, wanted);
        }
      onSaved(`Saved ${u.display_name} (${u.lan_id}).`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onSessionEnded(err.message);
      else setError(err instanceof Error ? err.message : "Couldn't save.");
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
          <div className="form-field--wide person-head">
            <span className="person-head__name">{u.display_name}</span>
            <span className="person-head__id">{u.lan_id}</span>
          </div>
          <fieldset className="form-field form-field--wide role-group">
            <legend>User groups</legend>
            {sources === null ? (
              <small>Loading…</small>
            ) : (
              <div className="perm-grid">
                {sources.map((s) => (
                  <div key={s.code} className="perm-grid__row" role="group" aria-label={s.name}>
                    <span className="perm-grid__group">{s.name}</span>
                    <div className="perm-grid__options">
                      {s.hierarchy!.groups.flatMap((g) =>
                        g.roles.map((r) => {
                          const key = `${s.code}:${g.type}`;
                          // You can't take away your own platform admin role.
                          const locked = isMe && s.code === "PLATFORM" && g.type === "ADMINS" && !!current[key]?.length;
                          return (
                            <label key={`${key}:${r}`} className="perm-grid__option">
                              <input type="checkbox" checked={chosen[key]?.has(r) ?? false} disabled={locked}
                                onChange={() => toggle(key, r)} />
                              {GROUP_LABEL[g.type] ?? g.name} - {roleName(r)}
                            </label>
                          );
                        }),
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </fieldset>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving || sources === null}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}
