// The upload control in the top bar. It's "controlled" — the actual upload
// logic lives in App (so drag-and-drop can reuse it); this component just shows
// the button + status and reports the chosen file back up via onFile.

import { useRef } from "react";

interface Props {
  busy: boolean;
  status: string;
  onFile: (file: File) => void;
  onCancel: () => void;
}

export function UploadPanel({ busy, status, onFile, onCancel }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="upload">
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.txt"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = ""; // allow re-uploading the same file
        }}
      />
      <button className="upload-btn" disabled={busy} onClick={() => inputRef.current?.click()}>
        {busy ? "Indexing…" : "Upload document"}
      </button>
      {busy && (
        <button className="cancel-upload" onClick={onCancel} title="Cancel upload">
          Cancel
        </button>
      )}
      {status && <span className="upload-status">{status}</span>}
    </div>
  );
}
