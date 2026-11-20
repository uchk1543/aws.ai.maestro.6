// 약속 2(docs/schema.md)의 모양. 칸 이름은 tools/models.py 와 docs/examples/ 와 똑같이 쓴다.
// 서버 쪽이 바뀌면 여기만 고친다.

export type DocType =
  | "bill_of_lading"
  | "commercial_invoice"
  | "packing_list"
  | "certificate_of_origin"
  | "unknown";

export const DOC_TYPE_KO: Record<DocType, string> = {
  bill_of_lading: "선하증권",
  commercial_invoice: "상업송장",
  packing_list: "포장명세서",
  certificate_of_origin: "원산지증명서",
  unknown: "알 수 없는 서류",
};

export type JobStatus = "queued" | "running" | "waiting_approval" | "done" | "failed";
export type Grade = "불일치" | "확인 필요" | "참고";
export type CheckedBy = "pdf_text" | "textract" | "model_reread" | "none";
export type HSStatus = "자동 확정" | "사람 확인 필요" | "사람 확정";
export type HSBy = "history" | "auto_match" | "human";
export type WmsStatus = "승인 대기" | "등록됨";
export type WmsBy = "auto" | "human";

// POST /api/uploads
export interface UploadRequestFile {
  name: string;
  content_type: string;
}
export interface UploadTarget {
  key: string;
  url: string;
}
export interface UploadsResponse {
  uploads: UploadTarget[];
}

// POST /api/jobs (doc_type 이 null 이면 에이전트가 분류한다)
export interface JobFile {
  key: string;
  doc_type: DocType | null;
}
export interface CreateJobResponse {
  job_id: string;
}

// GET /api/jobs/{id}
export interface Step {
  tool: string;
  summary: string;
  ok: boolean;
}
export interface IssueCell {
  doc: DocType;
  field: string;
  raw: string | null;
}
export interface Issue {
  rule_id: string;
  grade: Grade;
  cells: IssueCell[];
  suspect: DocType | null;
  evidence: string;
  checked_by: CheckedBy;
}
export interface HSCandidate {
  hs: string;
  name: string;
  reason: string;
}
export interface HSResult {
  line: number;
  status: HSStatus;
  by: HSBy | null;
  hs_code: string | null;
  candidates: HSCandidate[];
}
export interface DeclarationField {
  name: string;
  value: string | number | null;
  source: string;
}
export interface DeclarationDraft {
  fields: DeclarationField[];
  blank_fields: string[];
  pdf_url: string | null;
}
export interface WmsState {
  status: WmsStatus;
  by: WmsBy | null;
  wms_id?: string | null;
}
export interface JobResult {
  issues: Issue[];
  hs: HSResult[];
  declaration_draft: DeclarationDraft | null;
  wms: WmsState | null;
}
export interface Job {
  job_id: string;
  status: JobStatus;
  steps: Step[];
  result: JobResult | null;
  error?: string | null;
}
