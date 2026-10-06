import { errorText } from '../i18n';
export type Platform = "X" | "INSTAGRAM";
export type Role = "OWN" | "COMPETITOR";
export type TermType = "KEYWORD" | "HASHTAG";
export type ImportType = "OWN_POSTS" | "ACCOUNT_DAILY" | "TREND_POSTS" | "COMPETITOR_POSTS";
export type ImportStatus = "PROCESSING" | "SUCCESS" | "PARTIAL_ERROR" | "FAILED";
export type Project = { data_mode: "DEMO" | "LIVE"; project_id: string; name: string; description: string | null; is_active: boolean; platforms: Platform[]; created_at: string; updated_at: string };
export type SNSAccount = { account_id: string; project_id: string; platform: Platform; account_role: Role; account_name: string; display_name: string | null; platform_account_id: string | null; profile_url: string | null; is_active: boolean; created_at: string; updated_at: string };
export type WatchTerm = { term_id: string; term: string; normalized_term: string; term_type: TermType; is_active: boolean };
export type WatchTopic = { topic_id: string; project_id: string; topic_name: string; description: string | null; is_active: boolean; terms: WatchTerm[] };
export type RowError = { row: number | null; field: string; code: string; message: string };
export type ImportResult = { import_id?: string; status: ImportStatus; total_count?: number; success_count?: number; error_count?: number; errors: RowError[] };
export type ImportHistory = { import_id: string; import_type: ImportType; filename: string; total_count: number; success_count: number; error_count: number; status: ImportStatus; imported_at: string };
export type ImportHistoryDetail = ImportHistory & { error_detail: RowError[] };
export type HistoryPage = { items: ImportHistory[]; total: number; page: number; page_size: number; limit: number; offset: number };

export class ApiError extends Error {
  constructor(message: string, public status: number, public result?: ImportResult) { super(message); }
}
const base = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");
function object(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null; }
export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try { response = await fetch(`${base}/api/v1${path}`, { ...options, cache: "no-store" }); }
  catch { throw new ApiError(errorText(undefined,0), 0); }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    let message = "取得・保存に失敗しました。入力内容を確認し、再試行してください。";
    const code = object(data) && object(data.error) && typeof data.error.code === "string" ? data.error.code : undefined;
    const result = object(data) && data.status === "FAILED" && Array.isArray(data.errors) ? data as ImportResult : undefined;
    message = errorText(code ?? result?.errors[0]?.code, response.status);
    throw new ApiError(message, response.status, result);
  }
  return data as T;
}
function json(method: string, body: object): RequestInit { return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }; }
const projectPath = (id: string) => `/projects/${encodeURIComponent(id)}`;
export const api = {
  projects: () => apiFetch<Project[]>("/projects"),
  createProject: (body: { name: string; description: string | null; platforms: Platform[]; data_mode: Project["data_mode"] }) => apiFetch<Project>("/projects", json("POST", body)),
  updateProject: (id: string, body: Partial<Pick<Project, "name" | "description" | "is_active">>) => apiFetch<Project>(projectPath(id), json("PUT", body)),
  platforms: (id: string, platforms: Platform[]) => apiFetch<{ platforms: Platform[] }>(`${projectPath(id)}/platforms`, json("PUT", { platforms })),
  accounts: (id: string) => apiFetch<SNSAccount[]>(`${projectPath(id)}/accounts`),
  createAccount: (id: string, body: Pick<SNSAccount, "platform" | "account_role" | "account_name" | "display_name" | "platform_account_id" | "profile_url">) => apiFetch<SNSAccount>(`${projectPath(id)}/accounts`, json("POST", body)),
  updateAccount: (id: string, accountId: string, body: Partial<Pick<SNSAccount, "account_name" | "display_name" | "platform_account_id" | "profile_url" | "is_active">>) => apiFetch<SNSAccount>(`${projectPath(id)}/accounts/${accountId}`, json("PUT", body)),
  topics: (id: string) => apiFetch<WatchTopic[]>(`${projectPath(id)}/topics`),
  createTopic: (id: string, body: { topic_name: string; description: string | null }) => apiFetch<WatchTopic>(`${projectPath(id)}/topics`, json("POST", body)),
  updateTopic: (id: string, topicId: string, body: Partial<Pick<WatchTopic, "topic_name" | "description" | "is_active">>) => apiFetch<WatchTopic>(`${projectPath(id)}/topics/${topicId}`, json("PUT", body)),
  createTerm: (id: string, topicId: string, body: { term: string; term_type: TermType }) => apiFetch<WatchTerm>(`${projectPath(id)}/topics/${topicId}/terms`, json("POST", body)),
  updateTerm: (id: string, topicId: string, termId: string, body: Partial<Pick<WatchTerm, "term" | "term_type" | "is_active">>) => apiFetch<WatchTerm>(`${projectPath(id)}/topics/${topicId}/terms/${termId}`, json("PATCH", body)),
  importCsv: (id: string, type: ImportType, file: File) => { const body = new FormData(); body.append("import_type", type); body.append("file", file); return apiFetch<ImportResult>(`${projectPath(id)}/imports`, { method: "POST", body }); },
  histories: (id: string, page: number, status: string, type: string) => apiFetch<HistoryPage>(`${projectPath(id)}/imports?${new URLSearchParams({ page: String(page), page_size: "20", ...(status ? { status } : {}), ...(type ? { import_type: type } : {}) })}`),
  history: (id: string, importId: string) => apiFetch<ImportHistoryDetail>(`${projectPath(id)}/imports/${importId}`),
};
