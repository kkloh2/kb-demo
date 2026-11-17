import { useEffect, useRef, useState } from "react";
import { uploadDocuments, type DocRepoDocument } from "../../api/documents";
import { FileIcon, FolderIcon } from "../../components/Icons";
import { MessageBar } from "../../components/MessageBar";
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
  const [newFolder, setNewFolder] = useState("");
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

  const sub = newFolder.split("/").map((p) => p.trim()).filter(Boolean).join("/");
  const destination = [folder, sub].filter(Boolean).join("/");

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
      <div className="modal__body upload-dialog">
        {error && (
          <MessageBar className="alert" role="alert" onClose={() => setError(null)}>
            {error}
          </MessageBar>
        )}

        {target ? (
          <p className="modal__text">
            Upload a new version of <strong>{target.filename}</strong> in {folderLabel(target.folder)}. It's a draft until
            it's approved; version {target.version} stays published meanwhile.
          </p>
        ) : (
          <div className="form-grid">
            <label className="form-field">
              <span>Upload to</span>
              <select value={folder} onChange={(e) => setFolder(e.target.value)}>
                <option value="">Top level</option>
                {folders.map((f) => (
                  <option key={f} value={f}>
                    {folderLabel(f)}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field">
              <span>New folder (optional)</span>
              <input type="text" value={newFolder} onChange={(e) => setNewFolder(e.target.value)} maxLength={200}
                placeholder="e.g. 2027" />
              <small>Created inside the folder on the left.</small>
            </label>
          </div>
        )}

        <div className="upload-dialog__pick">
          <button type="button" className="btn-secondary" disabled={busy} onClick={() => filesInput.current?.click()}>
            <FileIcon />
            {target ? "Choose file" : "Choose files"}
          </button>
          {!target && (
            <button type="button" className="btn-secondary" disabled={busy} onClick={() => folderInput.current?.click()}>
              <FolderIcon />
              Choose a folder
            </button>
          )}
          <input ref={filesInput} type="file" multiple={!target}
            accept={target ? extOf(target.filename) : ALLOWED.join(",")} hidden
            onChange={(e) => pick(e.target.files, false)} data-testid="upload-files" />
          <input ref={folderInput} type="file" multiple hidden onChange={(e) => pick(e.target.files, true)}
            data-testid="upload-folder" />
        </div>

        {picked.length > 0 && (
          <>
            <p className="upload-dialog__summary">
              {plural(picked.length, "file", "files")} to {target ? "upload" : `upload to ${folderLabel(destination)}`}
              {leftOut ? ` · ${leftOut} left out (hidden, empty or not an allowed type)` : ""}. A file with the same name
              in the same folder becomes a new version of it.
            </p>
            <ul className="selection-list">
              {picked.slice(0, 200).map(({ file, path }) => (
                <li key={path}>
                  <span className={`doc-name__icon doc-name__icon--${extKind(file.name)}`}>
                    <FileIcon />
                  </span>
                  <span className="selection-list__name" title={path}>{path}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
      <div className="modal__footer">
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
