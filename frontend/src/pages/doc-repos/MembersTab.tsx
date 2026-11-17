import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { roleName } from "../../api/access";
import {
  listMembers,
  removeMember,
  setMemberGroups,
  type DocRepo,
  type Members,
  type RepoGroup,
  type RepoMember,
} from "../../api/doc-repos";
import { ApiError } from "../../api/http";
import { EditIcon, PlusIcon, SearchIcon } from "../../components/Icons";
import { MessageBar } from "../../components/MessageBar";
import { Modal } from "../../components/Modal";
import { SortHeader, useSort } from "../../components/Sort";
import { Pager, usePagination } from "../../components/Pager";
import { timeAgo } from "../../lib/time";
import { ErrorMessage, Notice, useErrors } from "../admin/common";

/** "default - Maker", or just the name when they hold no role in it. */
const groupRoles = (g: { name: string; roles: string[] }) =>
  g.roles.length ? `${g.name} - ${g.roles.map(roleName).join(", ")}` : g.name;

interface Props {
  token: string;
  docRepo: DocRepo;
  onSessionEnded: (message: string) => void;
}

/** Owner and admins: who is in the repository's user groups, with which roles. Changes take effect at once. */
export function MembersTab({ token, docRepo, onSessionEnded }: Props) {
  const [data, setData] = useState<Members | null>(null);
  const [editing, setEditing] = useState<RepoMember | "new" | null>(null);
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const { error, setError, fail } = useErrors(onSessionEnded);

  const load = useCallback(() => {
    listMembers(token, docRepo.id).then(setData).catch(fail);
  }, [token, docRepo.id, fail]);
  useEffect(load, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data?.members ?? []).filter((m) => !q || m.lan_id.toLowerCase().includes(q));
  }, [data, query]);
  const { sorted, sort, toggle } = useSort(filtered, {
    name: { value: (m) => m.display_name },
    lan_id: { value: (m) => m.lan_id },
    updated: { value: (m) => m.updated_at, desc: true },
  });
  const { rows, ...pager } = usePagination(sorted);

  return (
    <section className="panel" aria-labelledby="members-title">
      <div className="panel__head">
        <h2 id="members-title" className="panel__title">
          Users
        </h2>
      </div>

      <Notice onClose={() => setNotice(null)}>{notice}</Notice>

      {error ? (
        <ErrorMessage onClose={() => setError(null)}>{error}</ErrorMessage>
      ) : data === null ? (
        <p className="admin-message">Loading users…</p>
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
            <button type="button" className="btn-primary" onClick={() => { setEditing("new"); setNotice(null); }}>
              <PlusIcon />
              Add user
            </button>
          </div>

          {filtered.length === 0 ? (
            <p className="admin-message">{query ? `No one matches “${query}”.` : "Nobody yet."}</p>
          ) : (
            <>
              <table className="data-table members-table">
                <colgroup>
                  <col />
                  <col style={{ width: "120px" }} />
                  <col style={{ width: "280px" }} />
                  <col style={{ width: "120px" }} />
                  <col style={{ width: "48px" }} />
                </colgroup>
                <thead>
                  <tr>
                    <SortHeader label="Name" sortKey="name" sort={sort} onSort={toggle} />
                    <SortHeader label="LAN ID" sortKey="lan_id" sort={sort} onSort={toggle} />
                    <th scope="col">User group roles</th>
                    <SortHeader label="Last updated" sortKey="updated" sort={sort} onSort={toggle} />
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((m) => (
                    <tr key={m.lan_id}>
                      <td className="truncate">{m.display_name}</td>
                      <td className="muted truncate">{m.lan_id}</td>
                      <td>
                        <div className="stack">
                          {m.groups.map((g) => (
                            <span key={g.id} className="badge badge--neutral">
                              {groupRoles(g)}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td title={m.updated_at ? new Date(m.updated_at).toLocaleString() : undefined}>
                        {m.updated_at ? timeAgo(m.updated_at) : "—"}
                      </td>
                      <td className="kb-table__actions">
                        <button type="button" className="kb-icon-btn kb-icon-btn--brand" aria-label={`Edit ${m.display_name}`}
                          title="Edit" onClick={() => { setEditing(m); setNotice(null); }}>
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

          {/* Teams with access (data.team_grants) is hidden for now, at the user's request. */}
        </>
      )}

      <Modal
        open={editing !== null}
        title={editing === "new" ? "Add user" : "Edit user"}
        onClose={() => setEditing(null)}
      >
        {editing && data && (
          <MemberForm
            token={token}
            docRepoId={docRepo.id}
            groups={data.groups}
            grantable={data.grantable_roles}
            person={editing === "new" ? null : editing}
            onCancel={() => setEditing(null)}
            onSaved={(text) => {
              setEditing(null);
              setNotice(text);
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>
    </section>
  );
}

/** Add someone, or change their roles in each user group (untick everything to take them out). */
function MemberForm({
  token,
  docRepoId,
  groups,
  grantable,
  person,
  onCancel,
  onSaved,
  onSessionEnded,
}: {
  token: string;
  docRepoId: string;
  groups: RepoGroup[];
  grantable: string[];
  person: RepoMember | null; // null: add someone
  onCancel: () => void;
  onSaved: (message: string) => void;
  onSessionEnded: (message: string) => void;
}) {
  const isOwner = !!person?.roles.includes("OWNER");
  const current = (id: string) => person?.groups.find((g) => g.id === id)?.roles ?? [];
  const [lanId, setLanId] = useState(person?.lan_id ?? "");
  const [chosen, setChosen] = useState<Record<string, Set<string>>>(() =>
    Object.fromEntries(groups.map((g) => [g.id, new Set(person
      ? current(g.id).filter((r) => r !== "OWNER")
      : g.default ? ["VIEWER"] : [])])),
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function toggle(groupId: string, role: string) {
    setChosen((c) => {
      const next = new Set(c[groupId]);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return { ...c, [groupId]: next };
    });
  }

  const picked = groups.map((g) => ({ id: g.id, roles: grantable.filter((r) => chosen[g.id]?.has(r)) }));
  const anything = picked.some((g) => g.roles.length > 0);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const id = lanId.trim().toLowerCase();
    setError(null);
    setSaving(true);
    try {
      if (person && !anything && !isOwner) {
        await removeMember(token, docRepoId, person.lan_id);
        onSaved(`Removed ${person.display_name}.`);
      } else {
        const m = await setMemberGroups(token, docRepoId, id, picked);
        onSaved(person ? `Saved ${m.display_name}.` : `Added ${m.display_name}.`);
      }
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
          {person ? (
            <div className="form-field--wide person-head">
              <span className="person-head__name">{person.display_name}</span>
              <span className="person-head__id">{person.lan_id}</span>
            </div>
          ) : (
            <label className="form-field form-field--wide">
              <span>LAN ID</span>
              <input value={lanId} onChange={(e) => setLanId(e.target.value)} required autoFocus />
            </label>
          )}
          <fieldset className="form-field form-field--wide role-group">
            <legend>User groups</legend>
            <div className="perm-grid">
              {groups.map((g) => (
                <div key={g.id} className="perm-grid__row" role="group" aria-label={g.name}>
                  <span className="perm-grid__group">{g.name}</span>
                  <div className="perm-grid__options">
                    {isOwner && g.default && (
                      <label className="perm-grid__option">
                        <input type="checkbox" checked disabled />
                        {roleName("OWNER")}
                      </label>
                    )}
                    {grantable.map((r) => (
                      <label key={r} className="perm-grid__option">
                        <input type="checkbox" checked={chosen[g.id]?.has(r) ?? false} onChange={() => toggle(g.id, r)} />
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
        <button type="submit" className="btn-primary" disabled={saving || !lanId.trim() || (!person && !anything)}>
          {saving ? "Saving…" : person ? "Save" : "Add user"}
        </button>
      </div>
    </form>
  );
}
