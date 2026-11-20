// G2 업로드 화면: 여러 장 고르기 → 목록(X로 빼기, 서류 종류 고치기) → /api/uploads → S3 PUT → /api/jobs
import { useRef, useState } from "react";
import { ApiError, contentTypeOf, createJob, createUploads, putToS3 } from "../api";
import { navigate } from "../route";
import { DOC_TYPE_KO, type DocType } from "../types";

// 서버 한도와 같게 둔다 (agent/document_agent.py MAX_FILES, MAX_BYTES)
export const MAX_FILES = 10;
export const MAX_BYTES = 4_500_000;
const ACCEPT = ".pdf,.png,.jpg,.jpeg";

// 사용자가 고를 수 있는 서류 종류. null 은 에이전트가 분류한다.
const DOC_TYPE_OPTIONS: DocType[] = [
  "commercial_invoice",
  "packing_list",
  "bill_of_lading",
  "certificate_of_origin",
];

interface Picked {
  id: string;
  file: File;
  docType: DocType | null;
}

function sizeText(bytes: number): string {
  return bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)}MB` : `${Math.ceil(bytes / 1000)}KB`;
}

function fileId(f: File): string {
  return `${f.name}:${f.size}:${f.lastModified}`;
}

export function UploadPage() {
  const [picked, setPicked] = useState<Picked[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const tooBig = picked.filter((p) => p.file.size > MAX_BYTES);
  const tooMany = picked.length > MAX_FILES;
  const canUpload = picked.length > 0 && !busy && tooBig.length === 0 && !tooMany;

  function addFiles(list: FileList | null) {
    if (!list) return;
    setError(null);
    setPicked((prev) => {
      const seen = new Set(prev.map((p) => p.id));
      const added = Array.from(list)
        .filter((f) => !seen.has(fileId(f)))
        .map((f) => ({ id: fileId(f), file: f, docType: null }));
      return [...prev, ...added];
    });
    // 같은 파일을 뺐다가 다시 고를 수 있게 비운다
    if (inputRef.current) inputRef.current.value = "";
  }

  function remove(id: string) {
    setPicked((prev) => prev.filter((p) => p.id !== id));
  }

  function setDocType(id: string, docType: DocType | null) {
    setPicked((prev) => prev.map((p) => (p.id === id ? { ...p, docType } : p)));
  }

  async function upload() {
    setBusy(true);
    setError(null);
    try {
      const { uploads } = await createUploads(
        picked.map((p) => ({ name: p.file.name, content_type: contentTypeOf(p.file) })),
      );
      if (uploads.length !== picked.length) throw new Error("업로드 주소 수가 파일 수와 다릅니다");
      await Promise.all(uploads.map((u, i) => putToS3(u.url, picked[i].file, contentTypeOf(picked[i].file))));
      const { job_id } = await createJob(uploads.map((u, i) => ({ key: u.key, doc_type: picked[i].docType })));
      navigate(`/jobs/${encodeURIComponent(job_id)}`);
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : "업로드에 실패했습니다");
      setBusy(false);
    }
  }

  return (
    <section className="upload">
      <h1>파일 업로드</h1>
      <p className="hint">
        PDF · PNG · JPG, 한 번에 {MAX_FILES}개까지, 파일 하나 {sizeText(MAX_BYTES)}까지. 서류 종류를 비워 두면 자동으로 분류합니다.
      </p>

      <label className="file-pick">
        파일 고르기
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          disabled={busy}
          onChange={(e) => addFiles(e.target.files)}
        />
      </label>

      <div className="panel">
        <h2>선택된 파일 ({picked.length})</h2>
        {picked.length === 0 ? (
          <p className="empty">아직 고른 파일이 없습니다.</p>
        ) : (
          <ul className="file-list">
            {picked.map((p) => (
              <li key={p.id} className={p.file.size > MAX_BYTES ? "file-card invalid" : "file-card"}>
                <button
                  type="button"
                  className="file-remove"
                  aria-label={`${p.file.name} 빼기`}
                  disabled={busy}
                  onClick={() => remove(p.id)}
                >
                  ×
                </button>
                <div className="file-name">{p.file.name}</div>
                <div className="file-meta">
                  {sizeText(p.file.size)}
                  {p.file.size > MAX_BYTES && <span className="warn"> · 너무 큽니다</span>}
                </div>
                <label className="file-type">
                  서류 종류
                  <select
                    value={p.docType ?? ""}
                    disabled={busy}
                    onChange={(e) => setDocType(p.id, (e.target.value || null) as DocType | null)}
                  >
                    <option value="">자동 분류</option>
                    {DOC_TYPE_OPTIONS.map((t) => (
                      <option key={t} value={t}>
                        {DOC_TYPE_KO[t]}
                      </option>
                    ))}
                  </select>
                </label>
              </li>
            ))}
          </ul>
        )}
        {tooMany && (
          <p className="warn" role="alert">
            파일이 {picked.length}개입니다. {MAX_FILES}개까지 올릴 수 있습니다.
          </p>
        )}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <button type="button" className="primary" disabled={!canUpload} onClick={upload}>
        {busy ? "올리는 중…" : "업로드"}
      </button>
    </section>
  );
}
