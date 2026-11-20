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
  /** 그 행의 품명 (서류에 적힌 글자, FB07 #164). 없으면 화면은 "N행"만 */
  item_name?: string | null;
  /** 서류에 적힌 HS (적힌 그대로. 예: "9401.61") */
  doc_hs_code?: string | null;
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
  /** 모델이 칸으로 나타내지 못한 조건 (#165). 비어 있지 않으면 서버는 조회하지 않는다 */
  unsupported?: string[];
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
  /** 가드레일이 막았으면 그 이유 (E7 #152), 아니면 null */
  blocked?: string | null;
}
// GET /api/chat/{session_id} 대화 기록 (E6 #157, docs/examples/chat_history.json). 줄마다 질문 또는 답 하나
export interface ChatHistoryLine {
  session_id: string;
  ts: string;
  role: "user" | "assistant";
  text: string;
  filters: ChatFilters | null;
  count: number | null;
  rule: string | null;
  blocked: boolean | null;
  block_reason: string | null;
}
export interface ChatHistoryResponse {
  messages: ChatHistoryLine[];
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
  key: string; // S3 키. 서류 보기(GET /api/jobs/{id}/files)에서 이 파일을 찾는다
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

// GET /api/jobs/{id}/files (서류 보기, G11)
// 임시(제안 중): 서버 약속 제안 이슈가 합쳐지기 전 모양이다.
// 서버가 서류를 쪽 그림으로 만들어 주소를 주고, OCR 이 찾은 위치(bbox, 0~1 비율)를 표시(mark)로 준다.
// 화면은 위치를 계산하지 않고 받은 bbox 를 그대로 그린다.
export type MarkKind = "title" | "feature" | "field";
export interface DocMark {
  kind: MarkKind; // title: 서류 제목, feature: 분류에 쓴 특징 칸, field: 읽은 칸(오류 칸과 field 로 맞춘다)
  label: string;
  text: string;
  field: string | null; // kind=field 일 때 칸 경로. 예: "items[0].gross_kg" (IssueCell.field 와 같은 이름)
  page: number; // 1부터
  bbox: [number, number, number, number]; // left, top, width, height (0~1 비율)
}
export interface DocPage {
  url: string;
  width: number;
  height: number;
}
export interface ReadField {
  field: string;
  label: string;
  raw: string | null;
  value: string | number | null;
  unit: string | null;
  unreadable: string | null;
}
export interface JobFileView {
  key: string;
  file_name: string;
  doc_type: DocType;
  classified_by: ClassifiedBy;
  reason: string;
  // F7(#156): 원본 주소(미리 서명된 GET)와 형식, 읽은 칸. 가짜 응답(mockDocs)에는 없을 수 있다
  url?: string;
  content_type?: string;
  fields?: ReadField[];
  pages: DocPage[];
  marks: DocMark[];
}
export interface JobFilesResponse {
  files: JobFileView[];
}

// 문서 분류 내역 거르기 (F11 #195). 대시보드 통계를 누르면 이 조건으로 연다
export interface DocumentFilters {
  job_status?: JobStatus;
  grade?: Grade;
  rule_id?: string;
  hs?: "pending";
}

// GET /api/stats (대시보드, F11 #195). 숫자는 서버가 센 값 그대로 쓴다
export interface StatsResponse {
  today: string;
  todo: { waiting_approval: number; mismatch_jobs: number; hs_pending: number; unclassified: number; delayed: number };
  flow: { status: string; count: number }[];
  delayed: {
    bl_no: string;
    consignee: string;
    item: string;
    arrived_at: string;
    customs_status: string;
    days: number;
    job_id: string | null;
  }[];
  delay_rule: string;
  docs_by_type: Record<DocType, number>;
  auto: { finished: number; auto: number };
  top_rules: { rule_id: string; grade: Grade; count: number; example: string }[];
}
