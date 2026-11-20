// G2·G9 업로드 화면: 파일 고르기(끌어다 놓기도 된다) → 목록(오른쪽 위 X로 빼기) → /api/uploads → S3 PUT → /api/jobs
// 서류 종류는 고르지 않는다. 모두 doc_type null 로 보내고 에이전트가 자동으로 분류한다.
import { useRef, useState, type DragEvent } from "react";
import { ApiError, contentTypeOf, createJob, createUploads, putToS3 } from "../api";
import { Icon } from "../components/Icon";
import { navigate } from "../route";

// 서버 한도와 같게 둔다 (agent/document_agent.py MAX_FILES, MAX_BYTES)
export const MAX_FILES = 10;
export const MAX_BYTES = 4_500_000;
const EXTENSIONS = [".pdf", ".png", ".jpg", ".jpeg"];
const ACCEPT = EXTENSIONS.join(",");

interface Picked {
  id: string;
  file: File;
}

function sizeText(bytes: number): string {
  return bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)}MB` : `${Math.ceil(bytes / 1000)}KB`;
}

function fileId(f: File): string {
  return `${f.name}:${f.size}:${f.lastModified}`;
}

/** 확장자(.pdf .png .jpg .jpeg, 대소문자 무시)로 올릴 수 있는 파일인지 본다. 서버도 다시 검사한다. */
export function isAllowedFile(name: string): boolean {
  const lower = name.toLowerCase();
  return EXTENSIONS.some((ext) => lower.endsWith(ext));
}

/** 파일 카드에 적을 형식 글자. 예: "invoice.pdf" → "PDF" */
function extText(name: string): string {
  const m = name.match(/\.([a-z0-9]+)$/i);
  return m ? m[1].toUpperCase() : "파일";
}

export function UploadPage() {
  const [picked, setPicked] = useState<Picked[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState(0);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const tooBig = picked.filter((p) => p.file.size > MAX_BYTES);
  const tooMany = picked.length > MAX_FILES;
  const canUpload = picked.length > 0 && !busy && tooBig.length === 0 && !tooMany;

  function addFiles(list: FileList | null) {
    if (!list) return;
    const files = Array.from(list);
    const allowed = files.filter((f) => isAllowedFile(f.name));
    setSkipped(files.length - allowed.length);
    setError(null);
    setPicked((prev) => {
      const seen = new Set(prev.map((p) => p.id));
      const added = allowed.filter((f) => !seen.has(fileId(f))).map((f) => ({ id: fileId(f), file: f }));
      return [...prev, ...added];
    });
    // 같은 파일을 뺐다가 다시 고를 수 있게 비운다
    if (inputRef.current) inputRef.current.value = "";
  }

  function remove(id: string) {
    setPicked((prev) => prev.filter((p) => p.id !== id));
  }

  function onDragOver(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    if (!busy) setDragging(true);
  }

  function onDragLeave(e: DragEvent<HTMLLabelElement>) {
    // 칸 안의 글자 위로 옮겨 갈 때는 끄지 않는다
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    setDragging(false);
  }

  function onDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragging(false);
    if (!busy) addFiles(e.dataTransfer.files);
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
      const { job_id } = await createJob(uploads.map((u) => ({ key: u.key, doc_type: null })));
      navigate(`/jobs/${encodeURIComponent(job_id)}`);
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : "업로드에 실패했습니다");
      setBusy(false);
    }
  }

  const pickClass = ["file-pick", dragging && "dragging", busy && "disabled"].filter(Boolean).join(" ");

  return (
    <section className="upload">
      <div className="upload-intro">
        <h1>
          검토할 서류를
          <br className="pc-br" /> 올려 주세요
        </h1>
        <p className="lead lead-short">
          PDF · PNG · JPG, 한 번에 {MAX_FILES}개까지
          <br />
          서류 종류는 자동으로 분류합니다
        </p>
        <p className="lead lead-long">올린 서류는 자동으로 분류하고 서로 대조합니다.</p>
        <dl className="upload-rules">
          <div>
            <dt>형식</dt>
            <dd>PDF · PNG · JPG</dd>
          </div>
          <div>
            <dt>개수</dt>
            <dd>한 번에 {MAX_FILES}개까지</dd>
          </div>
          <div>
            <dt>크기</dt>
            <dd>파일 하나 {sizeText(MAX_BYTES)}까지</dd>
          </div>
          <div>
            <dt>서류 종류</dt>
            <dd>자동 분류</dd>
          </div>
        </dl>
      </div>

      <div className="upload-work">
        {/* 브라우저 기본 "파일 선택" 버튼은 보이지 않게만 숨기고(키보드·읽기 프로그램은 그대로), 큰 칸 전체를 누르게 한다 */}
        <label className={pickClass} onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}>
          <Icon name="plus" />
          <span>파일 고르기</span>
          <span className="file-pick-drop" aria-hidden="true">
            또는 여기로 끌어다 놓기
          </span>
          <input
            ref={inputRef}
            className="visually-hidden"
            type="file"
            multiple
            accept={ACCEPT}
            aria-label="파일 고르기"
            disabled={busy}
            onChange={(e) => addFiles(e.target.files)}
          />
        </label>
        {skipped > 0 && (
          <p className="warn" role="alert">
            PDF · PNG · JPG 파일만 올릴 수 있습니다. {skipped}개는 넣지 않았습니다.
          </p>
        )}

        <div className="files-head">
          <h2>
            선택된 파일 <span className="count">{picked.length}</span>
          </h2>
          <span className="hint">{MAX_FILES}개까지</span>
        </div>
        {picked.length === 0 ? (
          <p className="empty">아직 고른 파일이 없습니다.</p>
        ) : (
          <ul className="file-list">
            {picked.map((p) => (
              <li key={p.id} className={p.file.size > MAX_BYTES ? "file-card invalid" : "file-card"}>
                <span className="file-ext" aria-hidden="true">
                  {extText(p.file.name)}
                </span>
                <div className="file-body">
                  <div className="file-name" title={p.file.name}>
                    {p.file.name}
                  </div>
                  <div className="file-meta">
                    {sizeText(p.file.size)}
                    {p.file.size > MAX_BYTES && <span className="warn"> · 너무 큽니다</span>}
                  </div>
                </div>
                <button
                  type="button"
                  className="file-remove"
                  aria-label={`${p.file.name} 빼기`}
                  disabled={busy}
                  onClick={() => remove(p.id)}
                >
                  <Icon name="close" />
                </button>
              </li>
            ))}
          </ul>
        )}
        {tooMany && (
          <p className="warn" role="alert">
            파일이 {picked.length}개입니다. {MAX_FILES}개까지 올릴 수 있습니다.
          </p>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <div className="upload-dock">
          <button type="button" className="primary block" disabled={!canUpload} onClick={upload}>
            {busy ? "올리는 중…" : picked.length > 0 ? `${picked.length}개 업로드` : "업로드"}
          </button>
        </div>
      </div>
    </section>
  );
}
