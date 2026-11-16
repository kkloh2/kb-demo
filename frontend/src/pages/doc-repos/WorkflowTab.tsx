import { useCallback, useEffect, useState } from "react";
import { roleName } from "../../api/access";
import type { DocRepo } from "../../api/doc-repos";
import { ApiError } from "../../api/http";
import { getRepoWorkflow, setRepoWorkflow, type RepoWorkflow, type WorkflowChoice } from "../../api/workflows";
import { EditIcon } from "../../components/Icons";
import { MessageBar } from "../../components/MessageBar";
import { Modal } from "../../components/Modal";
import "../../styles/approvals.css";

interface Props {
  token: string;
  docRepo: DocRepo;
  onSessionEnded: (message: string) => void;
}

/** Owner and admins: which approval workflow this repository's submissions go through. */
export function WorkflowTab({ token, docRepo, onSessionEnded }: Props) {
  const [data, setData] = useState<RepoWorkflow | null>(null);
  const [changing, setChanging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fail = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
    else setError(e instanceof Error ? e.message : "Something went wrong.");
  }, [onSessionEnded]);

  useEffect(() => {
    getRepoWorkflow(token, docRepo.id).then(setData).catch(fail);
  }, [token, docRepo.id, fail]);

  const current = data?.current ?? null;

  return (
    <section className="panel" aria-labelledby="workflow-title">
      <div className="panel__head">
        <div>
          <h2 id="workflow-title" className="panel__title">
            Approval workflow
          </h2>
          {current && (
            <p className="panel__desc">
              New submissions go through <strong>{current.name}</strong> (version {current.version}).
            </p>
          )}
        </div>
        {data && (
          <button type="button" className="btn-primary" onClick={() => { setChanging(true); setNotice(null); }}>
            <EditIcon />
            Change workflow
          </button>
        )}
      </div>

      {notice && <MessageBar onClose={() => setNotice(null)}>{notice}</MessageBar>}
      {error && <MessageBar className="alert" role="alert" onClose={() => setError(null)}>{error}</MessageBar>}

      {!data ? (
        !error && <p className="admin-message">Loading…</p>
      ) : !current ? (
        <p className="admin-message">No workflow is chosen yet, so documents here can't be sent for approval.</p>
      ) : (
        <>
          {data.missing_groups.length > 0 && (
            <MessageBar className="alert" role="alert">
              This workflow needs {data.missing_groups.length === 1 ? "the user group" : "the user groups"}{" "}
              {data.missing_groups.map((g) => `“${g}”`).join(", ")} in {docRepo.name}. Add{" "}
              {data.missing_groups.length === 1 ? "it" : "them"} on the User groups tab, then give people roles in{" "}
              {data.missing_groups.length === 1 ? "it" : "them"} on the Users tab.
            </MessageBar>
          )}
          <WorkflowSteps workflow={current} />
        </>
      )}

      <Modal open={changing} title="Change workflow" onClose={() => setChanging(false)}>
        {changing && data && (
          <ChangeWorkflow
            data={data}
            onCancel={() => setChanging(false)}
            onChoose={async (id) => {
              try {
                const w = await setRepoWorkflow(token, docRepo.id, id);
                setData(w);
                setChanging(false);
                setNotice(`New submissions now go through ${w.current?.name}. Ones already waiting keep theirs.`);
              } catch (e) {
                setChanging(false);
                fail(e);
              }
            }}
          />
        )}
      </Modal>
    </section>
  );
}

/** A workflow's steps in plain words: each step and who acts on it. */
function WorkflowSteps({ workflow }: { workflow: WorkflowChoice }) {
  return (
    <ol className="flow-steps">
      {workflow.steps.map((s, i) => (
        <li key={s.id} className="flow-step">
          <span className="flow-step__num">{i + 1}</span>
          <div className="flow-step__body">
            <strong>{s.name}</strong>
            {s.role && s.user_group && (
              <p className="muted">
                {roleName(s.role)} in the user group “{s.user_group}”
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

function ChangeWorkflow({
  data,
  onCancel,
  onChoose,
}: {
  data: RepoWorkflow;
  onCancel: () => void;
  onChoose: (workflowId: string) => Promise<void>;
}) {
  const [chosen, setChosen] = useState(data.current?.id ?? data.options[0]?.id ?? "");
  const [saving, setSaving] = useState(false);
  const preview = data.options.find((o) => o.id === chosen) ?? null;
  const onlyOne = data.options.length <= 1;
  const changed = !!chosen && chosen !== data.current?.id;

  return (
    <>
      <div className="modal__body workflow-editor">
        {onlyOne ? (
          <p className="muted">
            {preview ? <><strong>{preview.name}</strong> is the only document workflow so far.</> : "There are no document workflows yet."}{" "}
            Platform admins add more under Approvals → Workflows.
          </p>
        ) : (
          <fieldset className="workflow-options">
            <legend className="visually-hidden">Workflow</legend>
            {data.options.map((o) => (
              <label key={o.id} className={`workflow-option${o.id === chosen ? " workflow-option--chosen" : ""}`}>
                <input type="radio" name="workflow" value={o.id} checked={o.id === chosen}
                  onChange={() => setChosen(o.id)} />
                <span className="workflow-option__body">
                  <span className="workflow-option__name">
                    {o.name} <span className="muted">v{o.version}</span>
                    {o.id === data.current?.id && <span className="badge badge--neutral">Current</span>}
                  </span>
                  <span className="workflow-option__steps">{o.steps.map((x) => x.name).join(" → ")}</span>
                </span>
              </label>
            ))}
          </fieldset>
        )}
        {preview && (
          <section className="meta-section">
            <h4 className="meta-section__title">Steps</h4>
            <WorkflowSteps workflow={preview} />
          </section>
        )}
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          {changed ? "Cancel" : "Close"}
        </button>
        {changed && (
          <button type="button" className="btn-primary" disabled={saving}
            onClick={async () => { setSaving(true); await onChoose(chosen); }}>
            {saving ? "Saving…" : "Use this workflow"}
          </button>
        )}
      </div>
    </>
  );
}
