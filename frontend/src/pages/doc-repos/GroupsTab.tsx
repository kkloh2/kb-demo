import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  createGroup,
  deleteGroup,
  listGroups,
  updateGroup,
  type DocRepo,
  type Groups,
  type RepoGroup,
} from "../../api/doc-repos";
import { ApiError } from "../../api/http";
import { EditIcon, PlusIcon, TrashIcon } from "../../components/Icons";
import { MessageBar } from "../../components/MessageBar";
import { Modal } from "../../components/Modal";
import { SortHeader, useSort } from "../../components/Sort";
import { Pager, usePagination } from "../../components/Pager";
import { timeAgo } from "../../lib/time";
import { ConfirmDelete, ErrorMessage, Notice, useErrors } from "../admin/common";

interface Props {
  token: string;
  docRepo: DocRepo;
  onSessionEnded: (message: string) => void;
}

/** Owner and admins: the repository's user groups. A group is a name; on the Users tab each person is
 * given their own roles in the groups they're in (e.g. "default": Maker for one, Checker for another). */
export function GroupsTab({ token, docRepo, onSessionEnded }: Props) {
  const [data, setData] = useState<Groups | null>(null);
  const [editing, setEditing] = useState<RepoGroup | "new" | null>(null);
  const [deleting, setDeleting] = useState<RepoGroup | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { error, setError, fail } = useErrors(onSessionEnded);

  const load = useCallback(() => {
    listGroups(token, docRepo.id).then(setData).catch(fail);
  }, [token, docRepo.id, fail]);
  useEffect(load, [load]);

  const { sorted, sort, toggle } = useSort(data?.groups ?? [], {
    name: { value: (g) => g.name },
    updated: { value: (g) => g.updated_at, desc: true },
  });
  const { rows, ...pager } = usePagination(sorted);

  return (
    <section className="panel" aria-labelledby="groups-title">
      <div className="panel__head">
        <h2 id="groups-title" className="panel__title">
          User groups
        </h2>
        <button type="button" className="btn-primary" onClick={() => { setEditing("new"); setNotice(null); }}>
          <PlusIcon />
          Add user group
        </button>
      </div>

      <Notice onClose={() => setNotice(null)}>{notice}</Notice>

      {error ? (
        <ErrorMessage onClose={() => setError(null)}>{error}</ErrorMessage>
      ) : data === null ? (
        <p className="admin-message">Loading user groups…</p>
      ) : (
        <>
          <table className="data-table members-table">
            <colgroup>
              <col />
              <col style={{ width: "140px" }} />
              <col style={{ width: "96px" }} />
            </colgroup>
            <thead>
              <tr>
                <SortHeader label="User group" sortKey="name" sort={sort} onSort={toggle} />
                <SortHeader label="Last updated" sortKey="updated" sort={sort} onSort={toggle} />
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((g) => (
                <tr key={g.id}>
                  <td className="truncate">
                    {g.name}
                    {g.default && <span className="muted"> (default)</span>}
                  </td>
                  <td title={new Date(g.updated_at).toLocaleString()}>{timeAgo(g.updated_at)}</td>
                  <td className="row-actions">
                    <button type="button" className="kb-icon-btn kb-icon-btn--brand" aria-label={`Edit ${g.name}`}
                      title="Edit" onClick={() => { setEditing(g); setNotice(null); }}>
                      <EditIcon />
                    </button>
                    {g.default ? (
                      <span className="kb-icon-btn kb-icon-btn--spacer" aria-hidden="true" />
                    ) : (
                      <button type="button" className="kb-icon-btn kb-icon-btn--brand" aria-label={`Delete ${g.name}`}
                        title="Delete" onClick={() => { setDeleting(g); setNotice(null); }}>
                        <TrashIcon />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager {...pager} />
        </>
      )}

      <Modal open={editing !== null} title={editing === "new" ? "Add user group" : "Edit user group"}
        onClose={() => setEditing(null)}>
        {editing && (
          <GroupForm
            token={token}
            docRepoId={docRepo.id}
            group={editing === "new" ? null : editing}
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

      <Modal open={deleting !== null} title="Delete user group" onClose={() => setDeleting(null)}>
        {deleting && (
          <ConfirmDelete
            message={
              <>
                Delete <strong>{deleting.name}</strong>?{" "}
                {deleting.member_count === 0
                  ? "Nobody is in it."
                  : deleting.member_count === 1
                    ? "The person in it loses the roles they have in it, straight away."
                    : `The ${deleting.member_count} people in it lose the roles they have in it, straight away.`}
                {" "}A workflow that names this group won't find it any more.
              </>
            }
            confirmLabel="Delete user group"
            onCancel={() => setDeleting(null)}
            onConfirm={async () => {
              await deleteGroup(token, docRepo.id, deleting.id);
              setDeleting(null);
              setNotice(`Deleted ${deleting.name}.`);
              load();
            }}
          />
        )}
      </Modal>
    </section>
  );
}

function GroupForm({
  token,
  docRepoId,
  group,
  onCancel,
  onSaved,
  onSessionEnded,
}: {
  token: string;
  docRepoId: string;
  group: RepoGroup | null; // null: add one
  onCancel: () => void;
  onSaved: (message: string) => void;
  onSessionEnded: (message: string) => void;
}) {
  const [name, setName] = useState(group?.name ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const body = { name: name.trim() };
      const saved = group ? await updateGroup(token, docRepoId, group.id, body) : await createGroup(token, docRepoId, body);
      onSaved(group ? `Saved ${saved.name}.` : `Added ${saved.name}. Give people roles in it on the Users tab.`);
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
          <label className="form-field form-field--wide">
            <span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={64} autoFocus />
          </label>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving || !name.trim()}>
          {saving ? "Saving…" : group ? "Save" : "Add user group"}
        </button>
      </div>
    </form>
  );
}
