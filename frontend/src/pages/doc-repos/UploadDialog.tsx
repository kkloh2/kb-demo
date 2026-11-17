import { useEffect, useRef, useState } from "react";
import { uploadDocuments, type DocRepoDocument } from "../../api/documents";
import { FileIcon, FolderIcon, UploadIcon } from "../../components/Icons";
import { MessageBar } from "../../components/MessageBar";
import { FolderTree } from "./FolderTree";
import { ALLOWED, extKind, extOf, folderLabel, plural } from "./docs-common";

/** Upload new documents into a chosen folder, or (with `target`) a new version of one document. */
interface Props {
  token: string;
  docRepoId: string;
  folders: string[]; // existing folders, to choose from
  initialFolder: string; // where the person was browsing
  target?: DocRepoDocument | null; // a new version of this document
  onCancel: () => void;
  onUploaded: (uploaded: DocRepoDocument[], leftOut: number) => void;
  onError: (e: unknown) => void;
}

type Picked = { file: File; path: string }; // path inside the destination folder

export function UploadDialog({ token, docRepoId, folders, initialFolder, target, onCancel, onUploaded, onError }: Props) {
  const [folder, setFolder] = useState(target ? target.folder : initialFolder);
  const [created, setCreated] = useState<string[]>([]); // new folders, made by the upload
  const [over, setOver] = useState(false); // something is being dragged over the drop area
  const [picked, setPicked] = useState<Picked[]>([]);
  const [leftOut, setLeftOut] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const filesInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  // Folder pickers need the non-standard webkitdirectory attribute.
  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", "");
  }, []);

  const destination = folder;
  const known = [...new Set([...folders, ...created])].sort((a, b) => a.localeCompare(b));
  const isNew = destination !== "" && !folders.includes(destination);

  function pick(list: FileList | null, fromFolder: boolean) {
    if (!list?.length) return;
    const all = [...list].map((file) => ({
      file,
      path: fromFolder && file.webkitRelativePath ? file.webkitRelativePath : file.name,
    }));
    const usable = all.filter(({ file }) => !file.name.startsWith(".") && ALLOWED.includes(extOf(file.name)) && file.size > 0);
    if (filesInput.current) filesInput.current.value = "";
    if (folderInput.current) folderInput.current.value = "";
    setError(null);
    if (target) {
      const [one] = usable;
      if (!one || extOf(one.file.name) !== extOf(target.filename)) {
        setError(`Choose a ${extOf(target.filename)} file: a new version keeps the document's type.`);
        return;
      }
      setPicked([one]);
      return;
    }
    if (!usable.length) {
      setError(`None of the ${all.length} files can be uploaded (allowed: ${ALLOWED.join(", ")}).`);
      return;
    }
    setPicked(usable);
    setLeftOut(all.length - usable.length);
  }

  async function upload() {
    setBusy(true);
    setError(null);
    try {
      const files = target
        ? picked.map(({ file }) => ({ file, path: [target.folder, target.filename].filter(Boolean).join("/") }))
        : picked.map(({ file, path }) => ({ file, path: [destination, path].filter(Boolean).join("/") }));
      onUploaded(await uploadDocuments(token, docRepoId, files), leftOut);
    } catch (e) {
      onError(e);
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className={`modal__body upload-dialog${target ? "" : " upload-dialog--split"}`}>
        {!target && (
          <div className="upload-dialog__tree">
            <span className="upload-dialog__label">Folders</span>
            <FolderTree folders={known} value={folder} onChange={setFolder}
              onNewFolder={(path) => setCreated((c) => (c.includes(path) ? c : [...c, path]))} />
          </div>
        )}

        <div className="upload-dialog__main">
          {error && (
            <MessageBar className="alert" role="alert" onClose={() => setError(null)}>
              {error}
            </MessageBar>
          )}

          {target ? (
            <p className="modal__text">
              A new version of <strong>{target.filename}</strong> in {folderLabel(target.folder)}. It's a draft until it's
              approved; version {target.version} stays published meanwhile.
            </p>
          ) : null}

          <div className="form-field">
            <span>{target ? "File" : "Files"}</span>
            {!target && (
              <p className="dest-line">
                <FolderIcon />
                <span className="truncate" title={folderLabel(destination)}>
                  Files go into <strong>{folderLabel(destination)}</strong>
                </span>
                {isNew && <span className="badge badge--neutral">New folder</span>}
              </p>
            )}
            {picked.length === 0 ? (
              <div className={`upload-dialog__drop${over ? " upload-dialog__drop--over" : ""}`}
                onDragOver={(e) => { e.preventDefault(); setOver(true); }}
                onDragLeave={() => setOver(false)}
                onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files, false); }}>
                <UploadIcon />
                <p>
                  {target ? "Drag the new file here, or " : "Drag files here, or "}
                  <button type="button" className="link-inline" disabled={busy} onClick={() => filesInput.current?.click()}>
                    {target ? "choose a file" : "choose files"}
                  </button>
                  {!target && (
                    <>
                      {" or "}
                      <button type="button" className="link-inline" disabled={busy} onClick={() => folderInput.current?.click()}>
                        a folder
                      </button>
                    </>
                  )}
                </p>
                <small>{target ? `A ${extOf(target.filename)} file` : `${ALLOWED.join(", ")} · up to 200 files`}</small>
              </div>
            ) : (
              <div className="picked">
                <div className="picked__head">
                  <span>
                    {plural(picked.length, "file", "files")}
                    {leftOut ? ` · ${leftOut} left out (hidden, empty or not an allowed type)` : ""}
                  </span>
                  <button type="button" className="btn-link" disabled={busy}
                    onClick={() => { setPicked([]); setLeftOut(0); }}>
                    {target ? "Choose a different file" : "Choose different files"}
                  </button>
                </div>
                <ul className="picked__list">
                  {picked.slice(0, 200).map(({ file, path }) => (
                    <li key={path}>
                      <span className={`doc-name__icon doc-name__icon--${extKind(file.name)}`}>
                        <FileIcon />
                      </span>
                      <span className="selection-list__name" title={path}>{path}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!target && <small>A file with the same name in the same folder becomes a new version of it.</small>}
            <input ref={filesInput} type="file" multiple={!target}
              accept={target ? extOf(target.filename) : ALLOWED.join(",")} hidden
              onChange={(e) => pick(e.target.files, false)} data-testid="upload-files" />
            <input ref={folderInput} type="file" multiple hidden onChange={(e) => pick(e.target.files, true)}
              data-testid="upload-folder" />
          </div>
        </div>
      </div>
      <div className="modal__footer needs-input">
        <button type="button" className="btn-secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn-primary" disabled={busy || picked.length === 0} onClick={upload}>
          {busy ? "Uploading…" : target ? "Upload new version" : `Upload ${picked.length || ""}`.trim()}
        </button>
      </div>
    </>
  );
}
