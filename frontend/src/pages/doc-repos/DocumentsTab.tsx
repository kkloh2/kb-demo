import { useCallback, useEffect, useMemo, useState } from "react";
import {
  deleteDocuments,
  downloadDocument,
  listDocuments,
  submitDocuments,
  type DocRepoDocument,
  type DocumentStatus,
} from "../../api/documents";
import { ApiError } from "../../api/http";
import type { DocRepo } from "../../api/doc-repos";
import { FileIcon, PlusIcon, UploadIcon } from "../../components/Icons";
import { MessageBar } from "../../components/MessageBar";
import { Modal } from "../../components/Modal";
import { DocumentPanel } from "./DocumentPanel";
import { InProgressList } from "./InProgressList";
import { PublishedList } from "./PublishedList";
import { UploadDialog } from "./UploadDialog";
import { allFolders, extKind, plural } from "./docs-common";

type View = "published" | "in_progress";
type Notice = { kind: "ok" | "error"; text: string } | null;

interface Props {
  token: string;
  docRepo: DocRepo;
  onSessionEnded: (message: string) => void;
}

/**
 * The repository's documents in two lists. Published: the approved version of each document, to
 * browse by folder and find by metadata (all that viewers see). In progress: what isn't approved yet
 * (drafts, waiting, changes requested, rejected), for makers, checkers and auditors, where makers
 * submit in bulk. Add uploads into a chosen folder; decisions happen on the Approvals page.
 */
export function DocumentsTab({ token, docRepo, onSessionEnded }: Props) {
  const { access } = docRepo;
  const canUpload = access.upload;
  const seesProgress = canUpload || access.roles.includes("CHECKER") || access.roles.includes("AUDITOR");
  const [view, setView] = useState<View>("published");
  const [published, setPublished] = useState<DocRepoDocument[] | null>(null);
  const [inProgress, setInProgress] = useState<DocRepoDocument[] | null>(seesProgress ? null : []);
  const [folder, setFolder] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  const [open, setOpen] = useState<{ id: string; published: boolean } | null>(null);
  const [uploading, setUploading] = useState<{ target: DocRepoDocument | null } | null>(null);
  const [deleting, setDeleting] = useState<DocRepoDocument | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  // Ticked documents, with the status each had when ticked: the server refuses the batch if any changed.
  const [selected, setSelected] = useState<Map<string, DocumentStatus>>(new Map());

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
      else setNotice({ kind: "error", text: e instanceof Error ? e.message : "Something went wrong." });
    },
    [onSessionEnded],
  );

  const load = useCallback(() => {
    Promise.all([
      listDocuments(token, docRepo.id, "published"),
      seesProgress ? listDocuments(token, docRepo.id, "in_progress") : Promise.resolve([]),
    ])
      .then(([pub, wip]) => {
        setPublished(pub);
        setInProgress(wip);
        // keep only ticks that still apply
        const now = new Map(wip.map((d) => [d.id, d]));
        setSelected((sel) => {
          const kept = new Map([...sel].filter(([id, st]) => now.get(id)?.status === st));
          return kept.size === sel.size ? sel : kept;
        });
      })
      .catch(fail);
  }, [token, docRepo.id, seesProgress, fail]);
  useEffect(load, [load]);

  const folders = useMemo(() => allFolders([...(published ?? []), ...(inProgress ?? [])]), [published, inProgress]);
  const workingOn = useMemo(() => new Set((inProgress ?? []).map((d) => d.id)), [inProgress]);
  const chosen = useMemo(() => (inProgress ?? []).filter((d) => selected.has(d.id)), [inProgress, selected]);

  // ---------------------------------------------------------------- actions
  async function run(label: string, work: () => Promise<string>) {
    setBusy(label);
    setNotice(null);
    try {
      setNotice({ kind: "ok", text: await work() });
    } catch (e) {
      fail(e);
      if (e instanceof ApiError && e.status === 409) setSelected(new Map());
    } finally {
      setBusy(null);
      load();
    }
  }

  const submitSelected = () => {
    const statuses = Object.fromEntries(selected);
    const n = selected.size;
    setConfirming(false);
    run("bulk-submit", async () => {
      await submitDocuments(token, docRepo.id, statuses);
      setSelected(new Map());
      return `Submitted ${plural(n, "document", "documents")} for approval.`;
    });
  };

  function uploaded(docs: DocRepoDocument[], leftOut: number) {
    setUploading(null);
    const count = (o: string) => docs.filter((d) => d.outcome === o).length;
    const parts = [
      count("new") && plural(count("new"), "new document", "new documents"),
      count("version") && plural(count("version"), "new version", "new versions"),
      count("replaced") && plural(count("replaced"), "replaced draft", "replaced drafts"),
    ].filter(Boolean);
    setNotice({
      kind: "ok",
      text:
        `Uploaded ${plural(docs.length, "file", "files")}: ${parts.join(", ")}. ` +
        (leftOut ? `Left out ${leftOut} (hidden, empty or not an allowed type). ` : "") +
        "They're in progress: check each one's metadata, then submit it for approval.",
    });
    setView("in_progress");
    load();
  }

  const showView = seesProgress ? view : "published";

  return (
    <div>
      <div className="docs-views">
        {seesProgress ? (
          <div className="segmented" role="tablist" aria-label="Documents">
            {(["published", "in_progress"] as View[]).map((v) => {
              const n = (v === "published" ? published : inProgress)?.length;
              return (
                <button key={v} type="button" role="tab" aria-selected={showView === v} className="segmented__item"
                  onClick={() => setView(v)}>
                  {v === "published" ? "Published" : "In progress"}
                  {n !== undefined && ` (${n})`}
                </button>
              );
            })}
          </div>
        ) : (
          <span />
        )}

        {canUpload && (
          <div className="toolbar__right bulk-actions">
            {showView === "in_progress" && (
              <>
                {selected.size > 0 && (
                  <span className="selection-count" aria-live="polite">
                    <strong>{selected.size} selected</strong>
                    <button type="button" className="btn-link" onClick={() => setSelected(new Map())}>
                      Clear
                    </button>
                  </span>
                )}
                <button type="button" className="btn-primary" disabled={selected.size === 0 || busy !== null}
                  title={selected.size === 0 ? "Tick drafts or documents sent back for changes to submit them together" : undefined}
                  onClick={() => setConfirming(true)}>
                  <UploadIcon />
                  {busy === "bulk-submit" ? "Submitting…" : "Submit for approval"}
                </button>
              </>
            )}
            <button type="button" className="btn-outline" disabled={busy !== null}
              onClick={() => setUploading({ target: null })}>
              <PlusIcon />
              Add
            </button>
          </div>
        )}
      </div>

      {notice && (
        <MessageBar className={notice.kind === "ok" ? "notice" : "notice notice--error"} onClose={() => setNotice(null)}>
          {notice.text}
        </MessageBar>
      )}

      {showView === "published" ? (
        <PublishedList
          docs={published}
          inProgress={canUpload ? workingOn : new Set()}
          canUpload={canUpload}
          folder={folder}
          onFolder={setFolder}
          onOpen={(d) => setOpen({ id: d.id, published: true })}
          onDownload={(d) => downloadDocument(token, d, true).catch(fail)}
          onNewVersion={(d) => setUploading({ target: d })}
        />
      ) : (
        <InProgressList
          docs={inProgress}
          canUpload={canUpload}
          selected={selected}
          onSelected={setSelected}
          onOpen={(d) => setOpen({ id: d.id, published: false })}
          onDownload={(d) => downloadDocument(token, d).catch(fail)}
          onSubmit={(d) =>
            run("submit", async () => {
              await submitDocuments(token, docRepo.id, { [d.id]: d.status });
              return `Submitted ${d.filename} for approval.`;
            })
          }
          onDelete={setDeleting}
        />
      )}

      <Modal open={open !== null} wide title="Document" onClose={() => setOpen(null)}>
        {open !== null && (
          <DocumentPanel
            token={token}
            docRepoId={docRepo.id}
            documentId={open.id}
            published={open.published}
            onClose={() => setOpen(null)}
            onChanged={(message) => {
              if (message) setNotice({ kind: "ok", text: message });
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>

      <Modal open={uploading !== null} wide={!uploading?.target}
        title={uploading?.target ? "Upload new version" : "Upload documents"}
        onClose={() => setUploading(null)}>
        {uploading && (
          <UploadDialog
            token={token}
            docRepoId={docRepo.id}
            folders={folders}
            initialFolder={folder}
            target={uploading.target}
            onCancel={() => setUploading(null)}
            onUploaded={uploaded}
            onError={(e) => {
              if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
            }}
          />
        )}
      </Modal>

      <Modal open={confirming} title="Submit for approval" onClose={() => setConfirming(false)}>
        {confirming && (
          <>
            <div className="modal__body bulk-confirm">
              <p className="modal__text">
                Submit {chosen.length === 1 ? "this document" : `these ${chosen.length} documents`} for approval? They're
                locked until a checker decides. If any changed after you selected it, none is submitted.
              </p>
              <ul className="selection-list">
                {chosen.map((d) => (
                  <li key={d.id}>
                    <span className={`doc-name__icon doc-name__icon--${extKind(d.filename)}`}>
                      <FileIcon />
                    </span>
                    <span className="selection-list__name" title={d.filename}>{d.filename}</span>
                    {d.folder && <span className="selection-list__meta" title={d.folder}>{d.folder}</span>}
                  </li>
                ))}
              </ul>
            </div>
            <div className="modal__footer">
              <button type="button" className="btn-secondary" onClick={() => setConfirming(false)}>
                Cancel
              </button>
              <button type="button" className="btn-primary" onClick={submitSelected}>
                <UploadIcon />
                Submit {chosen.length}
              </button>
            </div>
          </>
        )}
      </Modal>

      <Modal open={deleting !== null} title="Delete document" onClose={() => setDeleting(null)}>
        {deleting && (
          <>
            <div className="modal__body">
              <p className="modal__text">
                Delete {deleting.filename} and all its versions? It disappears from the repository and any request for
                its approval is withdrawn. It's kept on record.
              </p>
            </div>
            <div className="modal__footer">
              <button type="button" className="btn-secondary" onClick={() => setDeleting(null)}>
                Cancel
              </button>
              <button type="button" className="btn-danger" onClick={() => {
                const d = deleting;
                setDeleting(null);
                run("delete", async () => {
                  await deleteDocuments(token, docRepo.id, [d.id]);
                  return `Deleted ${d.filename}.`;
                });
              }}>
                Delete
              </button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}
