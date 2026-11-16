import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  addDefaultGrant,
  listDefaultGrants,
  listTeams,
  removeDefaultGrant,
  roleName,
  setTeamMembers,
  type DefaultGrant,
  type Team,
} from "../../api/access";
import { ApiError } from "../../api/http";
import { CloseIcon, EditIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { MessageBar } from "../../components/MessageBar";
import type { AdminTabProps } from "../AdminPage";
import { ErrorMessage, Notice, useErrors } from "./common";

/** What a team can be given on every document repository. */
const TEAM_ROLES = ["VIEWER", "AUDITOR"] as const;
const ROLE_HINT: Record<string, string> = {
  VIEWER: "Read documents and metadata",
  AUDITOR: "Read documents, metadata and the repository's activity",
};

/** Teams (Audit, Compliance): who is in them and the read-only access they get on every repository. */
export function TeamsTab({ token, onSessionEnded }: AdminTabProps) {
  const [teams, setTeams] = useState<Team[] | null>(null);
  const [grants, setGrants] = useState<DefaultGrant[]>([]);
  const [editing, setEditing] = useState<Team | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { error, setError, fail } = useErrors(onSessionEnded);

  const load = useCallback(() => {
    Promise.all([listTeams(token), listDefaultGrants(token)])
      .then(([t, g]) => {
        setTeams(t);
        setGrants(g.filter((x) => x.system === "DOC_HUB"));
      })
      .catch(fail);
  }, [token, fail]);
  useEffect(load, [load]);

  const rolesOf = (code: string) => grants.filter((g) => g.team === code);

  return (
    <section className="panel" aria-labelledby="teams-title">
      <div className="panel__head">
        <div>
          <h2 id="teams-title" className="panel__title">
            Teams
          </h2>
          <p className="panel__desc">
            Control functions such as audit and compliance. A team's access applies to every document repository,
            including new ones, and is read-only.
          </p>
        </div>
      </div>

      <Notice onClose={() => setNotice(null)}>{notice}</Notice>

      {error ? (
        <ErrorMessage onClose={() => setError(null)}>{error}</ErrorMessage>
      ) : teams === null ? (
        <p className="admin-message">Loading teams…</p>
      ) : (
        <table className="data-table members-table data-table--wrap">
          <colgroup>
            <col style={{ width: "20%" }} />
            <col />
            <col style={{ width: "28%" }} />
            <col style={{ width: "48px" }} />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">Team</th>
              <th scope="col">Members</th>
              <th scope="col">Access on every repository</th>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {teams.map((t) => (
              <tr key={t.code}>
                <td>{t.name}</td>
                <td>
                  {t.members.length ? (
                    t.members.map((m) => m.lan_id).join(", ")
                  ) : (
                    <span className="muted">Nobody yet</span>
                  )}
                </td>
                <td>
                  {rolesOf(t.code).length ? (
                    rolesOf(t.code).map((g) => roleName(g.role)).join(", ")
                  ) : (
                    <span className="muted">None</span>
                  )}
                </td>
                <td className="kb-table__actions">
                  <button type="button" className="kb-icon-btn kb-icon-btn--brand" aria-label={`Edit ${t.name}`}
                    title="Edit" onClick={() => setEditing(t)}>
                    <EditIcon />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <Modal open={editing !== null} title={editing ? `Edit ${editing.name}` : ""} onClose={() => setEditing(null)}>
        {editing && (
          <TeamForm
            token={token}
            team={editing}
            grants={rolesOf(editing.code)}
            onCancel={() => setEditing(null)}
            onSaved={() => {
              setNotice(`Saved ${editing.name}.`);
              setEditing(null);
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>
    </section>
  );
}

function TeamForm({
  token,
  team,
  grants,
  onCancel,
  onSaved,
  onSessionEnded,
}: {
  token: string;
  team: Team;
  grants: DefaultGrant[];
  onCancel: () => void;
  onSaved: () => void;
  onSessionEnded: (message: string) => void;
}) {
  const [members, setMembers] = useState<string[]>(team.members.map((m) => m.lan_id));
  const [lanId, setLanId] = useState("");
  const [roles, setRoles] = useState<Set<string>>(new Set(grants.map((g) => g.role)));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function add() {
    const id = lanId.trim().toLowerCase();
    if (id && !members.includes(id)) setMembers([...members, id]);
    setLanId("");
  }

  function toggle(role: string) {
    setRoles((r) => {
      const next = new Set(r);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return next;
    });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const before = team.members.map((m) => m.lan_id).sort().join();
      if ([...members].sort().join() !== before) await setTeamMembers(token, team.code, members);
      for (const g of grants) if (!roles.has(g.role)) await removeDefaultGrant(token, g.id);
      for (const r of roles) if (!grants.some((g) => g.role === r)) await addDefaultGrant(token, team.code, r);
      onSaved();
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
          <div className="form-field form-field--wide">
            <span>Members</span>
            <div className="team-add">
              <input value={lanId} onChange={(e) => setLanId(e.target.value)} placeholder="LAN ID" aria-label="LAN ID"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    add();
                  }
                }} />
              <button type="button" className="btn-secondary" onClick={add} disabled={!lanId.trim()}>
                Add
              </button>
            </div>
            {members.length ? (
              <ul className="team-members">
                {members.map((m) => (
                  <li key={m}>
                    {m}
                    <button type="button" className="kb-icon-btn" aria-label={`Remove ${m}`} title="Remove"
                      onClick={() => setMembers(members.filter((x) => x !== m))}>
                      <CloseIcon />
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <small className="muted">Nobody yet.</small>
            )}
          </div>
          <fieldset className="form-field form-field--wide role-group">
            <legend>Access on every repository</legend>
            <div className="team-roles">
              {TEAM_ROLES.map((r) => (
                <label key={r} className="team-role">
                  <input type="checkbox" checked={roles.has(r)} onChange={() => toggle(r)} />
                  <span>
                    <span className="team-role__name">{roleName(r)}</span>
                    <span className="team-role__hint">{ROLE_HINT[r]}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}
