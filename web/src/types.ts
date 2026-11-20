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

// POST /api/jobs/{id}/hs
export interface HSChoice {
  line: number;
  hs: string;
}
export interface ChooseHsResponse {
  declaration_draft: DeclarationDraft;
}

// POST /api/jobs/{id}/approve (불일치가 남았으면 409)
export interface ApproveResponse {
  wms: { status: WmsStatus; wms_id: string | null };
}

// POST /api/chat (docs/examples/chat_response.json)
export type Period = "today" | "this_week" | "last_week" | "range";
export interface ChatRequest {
  session_id: string;
  message: string;
}
export interface ChatFilters {
  status: string | null;
  period: Period | null;
  date_from?: string | null;
  date_to?: string | null;
}
export interface PeriodResolved {
  from: string;
  to: string;
}
export interface Shipment {
  bl_no: string;
  consignee: string;
  item: string;
  arrived_at: string;
  customs_status: string;
  last_event_at: string;
  job_id: string | null;
}
export interface ChatResponse {
  answer: string;
  filters: ChatFilters;
  period_resolved: PeriodResolved | null;
  rows: Shipment[];
}
// GET /api/documents (문서 분류 내역, G10)
// 임시(제안 중): 서버 약속 제안 이슈가 합쳐지기 전 모양이다. 합쳐지면 tools/models.py·docs/examples/documents.json 과 맞춘다.
export type ClassifiedBy = "model" | "user";
export const DOC_TYPES: DocType[] = [
  "commercial_invoice",
  "packing_list",
  "bill_of_lading",
  "certificate_of_origin",
  "unknown",
];
export interface DocumentRecord {
  job_id: string;
  file_name: string;
  doc_type: DocType;
  classified_by: ClassifiedBy;
  reason: string;
  doc_no: string | null;
  consignee: string | null;
  job_status: JobStatus;
  created_at: string;
}
export interface DocumentsResponse {
  counts: Record<DocType, number>;
  items: DocumentRecord[];
  next_cursor: string | null;
}
