import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../api/http";
import {
  listMembers,
  DOC_REPO_ROLE_NAMES,
  DOC_REPO_ROLES,
  removeMember,
  setMemberRoles,
  type Member,
  type DocRepo,
  type DocRepoRole,
} from "../../api/doc-repos";
import { PlusIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { ConfirmDelete, ErrorMessage, Notice, useErrors } from "../admin/common";

const ROLE_HELP: Record<DocRepoRole, string> = {
  MAKER: "Uploads documents and fills in their metadata",
  CHECKER: "Approves or rejects what makers submit",
  VIEWER: "Sees the repository's approved documents",
};
const EXCLUSIVE: Partial<Record<DocRepoRole, DocRepoRole>> = { MAKER: "CHECKER", CHECKER: "MAKER" };

interface Props {
  token: string;
  docRepo: DocRepo;
  onSessionEnded: (message: string) => void;
}

/** Department admins: who holds which role in this doc-repo. Changes take effect immediately. */
export function MembersTab({ token, docRepo, onSessionEnded }: Props) {
  const [members, setMembers] = useState<Member[] | null>(null);
  const [editing, setEditing] = useState<{ member: Member | null } | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { error, fail } = useErrors(onSessionEnded);

  const load = useCallback(() => {
    listMembers(token, docRepo.id).then(setMembers).catch(fail);
  }, [token, docRepo.id, fail]);
  useEffect(load, [load]);

  return (
    <section className="panel" aria-labelledby="members-title">
      <div className="panel__head">
        <div>
          <h2 id="members-title" className="panel__title">
            Members
          </h2>
          <p className="panel__desc">
            Makers upload, checkers approve or reject, viewers see approved documents. Department admins of{" "}
            {docRepo.department.name} see every repository's documents without being listed here.
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={() => setEditing({ member: null })}>
          <PlusIcon />
          Add member
        </button>
      </div>

      <Notice>{notice}</Notice>

      {error ? (
        <ErrorMessage>{error}</ErrorMessage>
      ) : members === null ? (
        <p className="admin-message">Loading members…</p>
      ) : members.length === 0 ? (
        <p className="admin-message">No members yet. Use Add member to give someone a role in this repository.</p>
      ) : (
        <table className="data-table">
          <colgroup>
            <col style={{ width: "28%" }} />
            <col style={{ width: "28%" }} />
            <col />
            <col style={{ width: "128px" }} />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Email</th>
              <th scope="col">Repository roles</th>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.lan_id}>
                <td>
                  <div className="person">
                    <span className="person__name">{m.display_name}</span>
                    <span className="person__id">
                      {m.lan_id}
                      {m.title ? ` · ${m.title}` : ""}
                    </span>
                  </div>
                </td>
                <td className="truncate">{m.email}</td>
                <td>
                  {m.roles.map((r) => (
                    <span key={r} className="badge">
                      {DOC_REPO_ROLE_NAMES[r]}
                    </span>
                  ))}
                </td>
                <td className="row-actions">
                  <button type="button" className="btn-link" onClick={() => setEditing({ member: m })}>
                    Edit
                  </button>
                  <button type="button" className="btn-link btn-link--danger" onClick={() => setRemoving(m)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <Modal
        open={editing !== null}
        title={editing?.member ? `Roles for ${editing.member.display_name}` : "Add member"}
        onClose={() => setEditing(null)}
      >
        {editing && (
          <MemberForm
            token={token}
            docRepoId={docRepo.id}
            existing={editing.member}
            onCancel={() => setEditing(null)}
            onSaved={(m) => {
              setEditing(null);
              setNotice(m.roles.length
                ? `${m.display_name} is now ${m.roles.map((r) => DOC_REPO_ROLE_NAMES[r].toLowerCase()).join(" and ")} here.`
                : `Removed ${m.display_name}.`);
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>

      <Modal open={removing !== null} title="Remove member" onClose={() => setRemoving(null)}>
        {removing && (
          <ConfirmDelete
            message={<>Remove <strong>{removing.display_name}</strong> ({removing.lan_id}) from {docRepo.name}? They lose
              access to its documents straight away.</>}
            confirmLabel="Remove member"
            onCancel={() => setRemoving(null)}
            onConfirm={async () => {
              await removeMember(token, docRepo.id, removing.lan_id);
              setRemoving(null);
              setNotice(`Removed ${removing.display_name}.`);
              load();
            }}
          />
        )}
      </Modal>
    </section>
  );
}

function MemberForm({
  token,
  docRepoId,
  existing,
  onCancel,
  onSaved,
  onSessionEnded,
}: {
  token: string;
  docRepoId: number;
  existing: Member | null;
  onCancel: () => void;
  onSaved: (m: Member) => void;
  onSessionEnded: (message: string) => void;
}) {
  const [lanId, setLanId] = useState(existing?.lan_id ?? "");
  const [roles, setRoles] = useState<Set<DocRepoRole>>(new Set(existing?.roles ?? ["VIEWER"]));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function toggle(role: DocRepoRole) {
    setRoles((current) => {
      const next = new Set(current);
      if (next.has(role)) next.delete(role);
      else {
        next.add(role);
        const other = EXCLUSIVE[role];
        if (other) next.delete(other); // one person can't be both maker and checker
      }
      return next;
    });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      onSaved(await setMemberRoles(token, docRepoId, lanId.trim(), DOC_REPO_ROLES.filter((r) => roles.has(r))));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onSessionEnded(err.message);
      else setError(err instanceof Error ? err.message : "Couldn't save the member.");
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="modal__body">
        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        <div className="form-grid">
          <label className="form-field form-field--wide">
            <span>LAN ID</span>
            <input value={lanId} onChange={(e) => setLanId(e.target.value)} readOnly={existing !== null}
              placeholder="e.g. alex.tan" required autoFocus={existing === null} />
            {!existing && <small>They need to have signed in to Data Hub once, or been added by a system admin.</small>}
          </label>
          <fieldset className="form-field form-field--wide role-group">
            <legend>Repository roles</legend>
            <div className="role-options">
              {DOC_REPO_ROLES.map((r) => (
                <label key={r} className="check check--block">
                  <input type="checkbox" checked={roles.has(r)} onChange={() => toggle(r)} />
                  <span>
                    <strong>{DOC_REPO_ROLE_NAMES[r]}</strong>
                    <small>{ROLE_HELP[r]}</small>
                  </span>
                </label>
              ))}
            </div>
            <small>Maker and checker can't both be held in one repository.</small>
          </fieldset>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving || roles.size === 0}>
          {saving ? "Saving…" : existing ? "Save" : "Add member"}
        </button>
      </div>
    </form>
  );
}
