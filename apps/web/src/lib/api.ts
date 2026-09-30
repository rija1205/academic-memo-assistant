const apiUrl = process.env.NEXT_PUBLIC_AUTH_API_URL ?? "/api/backend";
const csrfCookieName = process.env.NEXT_PUBLIC_CSRF_COOKIE_NAME ?? "ama_csrf";
let csrfToken = "";

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
  email_verified: boolean;
  is_active: boolean;
  created_at: string;
}

export interface AuthResponse {
  user: AuthUser;
  csrf_token: string;
}

export interface SessionSummary {
  id: string;
  current: boolean;
  created_at: string;
  last_seen_at: string | null;
  expires_at: string;
  user_agent: string | null;
}

export type ProjectStatus = "draft" | "in_progress" | "completed" | "archived";
export type EducationLevel = "licence" | "master" | "doctorat" | "other";
export type SectionStatus = "empty" | "in_progress" | "complete";

export interface ProjectSummary {
  id: string;
  title: string;
  domain: string | null;
  status: ProjectStatus;
  access_role: "owner" | "editor" | "reader";
  education_level: EducationLevel;
  institution: string | null;
  author_name: string | null;
  supervisor_name: string | null;
  academic_year: string | null;
  thesis_type: string;
  bibliography_style: string;
  progress: number;
  section_count: number;
  completed_sections: number;
  in_progress_sections: number;
  empty_sections: number;
  source_count: number;
  reference_count: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface Project extends ProjectSummary {
  problem_statement: string | null;
  general_objective: string | null;
  specific_objectives: string[];
  hypotheses: string[];
  keywords: string[];
}

export interface OutlineNode {
  id: string;
  project_id: string;
  parent_id: string | null;
  section_id: string;
  kind: "section" | "subsection";
  title: string;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface Section {
  id: string;
  project_id: string;
  outline_node_id: string;
  title: string;
  content: Record<string, unknown>;
  plain_text: string;
  status: SectionStatus;
  word_count: number;
  version: number;
  last_saved_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SectionRevision {
  id: string;
  section_id: string;
  project_id: string;
  version: number;
  title: string;
  content: Record<string, unknown>;
  plain_text: string;
  word_count: number;
  status: SectionStatus;
  change_summary: string | null;
  created_by: string | null;
  restored_from_id: string | null;
  created_at: string;
}

export function getSafeNext(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/dashboard";
  return value;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function readCookie(name: string): string {
  if (typeof document === "undefined") return "";
  const prefix = `${name}=`;
  const value = document.cookie.split("; ").find((cookie) => cookie.startsWith(prefix));
  return value ? decodeURIComponent(value.slice(prefix.length)) : "";
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  let message = "Une erreur est survenue.";
  try {
    const body = (await response.json()) as {
      detail?: string | Array<{ msg?: string }> | { message?: string; code?: string };
    };
    if (typeof body.detail === "string") {
      message = body.detail;
    } else if (body.detail && !Array.isArray(body.detail) && typeof body.detail === "object") {
      message = body.detail.message || message;
    } else if (Array.isArray(body.detail)) {
      const details = body.detail
        .map((item) => item.msg)
        .filter((item): item is string => Boolean(item));
      if (details.length > 0) message = details.join(" ");
    }
  } catch {
    // Keep the generic error message when the response is not JSON.
  }
  throw new ApiError(response.status, message);
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const method = options.method?.toUpperCase() ?? "GET";
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (method !== "GET" && method !== "HEAD") {
    const token = csrfToken || readCookie(csrfCookieName);
    if (token) headers.set("X-CSRF-Token", token);
  }

  const response = await fetch(`${apiUrl}${path}`, {
    ...options,
    headers,
    credentials: "include",
    cache: "no-store",
  });
  return parseResponse<T>(response);
}

async function requestFormData<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(`${apiUrl}${path}`, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    headers: {
      "X-CSRF-Token": readCookie(csrfCookieName) ?? "",
    },
    body: form,
  });
  return parseResponse<T>(response);
}

async function requestMutation<T>(path: string, options: RequestInit): Promise<T> {
  try {
    return await request<T>(path, options);
  } catch (error) {
    if (
      error instanceof ApiError
      && error.status === 403
      && error.message.toLowerCase().includes("csrf")
    ) {
      await getCsrfToken(true);
      return request<T>(path, options);
    }
    throw error;
  }
}

export async function getCsrfToken(force = false): Promise<string> {
  if (csrfToken && !force) return csrfToken;
  const response = await request<{ csrf_token: string }>("/api/auth/csrf");
  csrfToken = response.csrf_token;
  return csrfToken;
}

export async function register(input: {
  email: string;
  password: string;
  display_name?: string;
}): Promise<AuthResponse> {
  await getCsrfToken();
  const response = await requestMutation<AuthResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(input),
  });
  csrfToken = response.csrf_token;
  return response;
}

export async function login(input: { email: string; password: string }): Promise<AuthResponse> {
  await getCsrfToken();
  const response = await requestMutation<AuthResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(input),
  });
  csrfToken = response.csrf_token;
  return response;
}

export async function getCurrentUser(): Promise<AuthUser> {
  return request<AuthUser>("/api/auth/me");
}

export async function updateProfile(displayName: string | null): Promise<AuthUser> {
  await getCsrfToken();
  return requestMutation<AuthUser>("/api/auth/profile", {
    method: "PATCH",
    body: JSON.stringify({ display_name: displayName }),
  });
}

export async function logout(): Promise<void> {
  await getCsrfToken();
  await requestMutation<{ message: string }>("/api/auth/logout", { method: "POST" });
  csrfToken = "";
}

export async function requestPasswordReset(email: string): Promise<{ message: string; reset_token?: string | null }> {
  await getCsrfToken();
  return requestMutation<{ message: string; reset_token?: string | null }>("/api/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function resetPassword(token: string, password: string): Promise<{ message: string }> {
  await getCsrfToken();
  const response = await requestMutation<{ message: string }>("/api/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  });
  csrfToken = "";
  return response;
}

export async function getGoogleStatus(): Promise<boolean> {
  const response = await request<{ enabled: boolean }>("/api/auth/google/status");
  return response.enabled;
}

export async function redirectToGoogle(next = "/dashboard"): Promise<void> {
  await getCsrfToken();
  const response = await requestMutation<{ authorization_url: string }>(
    `/api/auth/google/start?next=${encodeURIComponent(next)}`,
    { method: "POST" },
  );
  window.location.assign(response.authorization_url);
}

export async function listProjects(): Promise<ProjectSummary[]> {
  return request<ProjectSummary[]>("/api/projects");
}

export interface ProjectInput {
  title: string;
  domain?: string | null;
  institution?: string | null;
  education_level?: EducationLevel;
  author_name?: string | null;
  supervisor_name?: string | null;
  academic_year?: string | null;
  problem_statement?: string | null;
  general_objective?: string | null;
  specific_objectives?: string[];
  hypotheses?: string[];
  keywords?: string[];
  thesis_type?: string;
  bibliography_style?: string;
}

export async function createProject(input: ProjectInput): Promise<Project> {
  await getCsrfToken();
  return requestMutation<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function getProject(projectId: string): Promise<Project> {
  return request<Project>(`/api/projects/${projectId}`);
}

export async function updateProject(
  projectId: string,
  input: Partial<ProjectInput> & { status?: ProjectStatus },
): Promise<Project> {
  await getCsrfToken();
  return requestMutation<Project>(`/api/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function archiveProject(projectId: string): Promise<Project> {
  await getCsrfToken();
  return requestMutation<Project>(`/api/projects/${projectId}/archive`, { method: "POST" });
}

export async function duplicateProject(projectId: string, title?: string): Promise<Project> {
  await getCsrfToken();
  return requestMutation<Project>(`/api/projects/${projectId}/duplicate`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export async function deleteProject(projectId: string): Promise<void> {
  await getCsrfToken();
  await requestMutation<{ message: string }>(`/api/projects/${projectId}`, { method: "DELETE" });
}

export async function getProjectOutline(projectId: string): Promise<OutlineNode[]> {
  return request<OutlineNode[]>(`/api/projects/${projectId}/outline`);
}

export async function createOutlineNode(
  projectId: string,
  input: { parent_id?: string | null; kind: "section" | "subsection"; title: string },
): Promise<OutlineNode> {
  await getCsrfToken();
  return requestMutation<OutlineNode>(`/api/projects/${projectId}/outline`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateOutlineNode(
  projectId: string,
  nodeId: string,
  input: { parent_id?: string | null; kind?: "section" | "subsection"; title?: string; position?: number },
): Promise<OutlineNode> {
  await getCsrfToken();
  return requestMutation<OutlineNode>(`/api/projects/${projectId}/outline/${nodeId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function reorderProjectOutline(
  projectId: string,
  moves: { node_id: string; parent_id: string | null; position: number }[],
): Promise<OutlineNode[]> {
  await getCsrfToken();
  return requestMutation<OutlineNode[]>(`/api/projects/${projectId}/outline/reorder`, {
    method: "POST",
    body: JSON.stringify({ moves }),
  });
}

export async function deleteOutlineNode(projectId: string, nodeId: string): Promise<void> {
  await getCsrfToken();
  await requestMutation<{ message: string }>(`/api/projects/${projectId}/outline/${nodeId}`, {
    method: "DELETE",
  });
}

export async function duplicateOutlineNode(projectId: string, nodeId: string): Promise<OutlineNode> {
  await getCsrfToken();
  return requestMutation<OutlineNode>(`/api/projects/${projectId}/outline/${nodeId}/duplicate`, {
    method: "POST",
  });
}

export async function getSection(projectId: string, sectionId: string): Promise<Section> {
  return request<Section>(`/api/projects/${projectId}/sections/${sectionId}`);
}

export async function saveSectionContent(
  projectId: string,
  sectionId: string,
  input: {
    content: Record<string, unknown>;
    plain_text: string;
    status?: SectionStatus;
    expected_version: number;
    change_summary?: string;
  },
): Promise<Section> {
  await getCsrfToken();
  return requestMutation<Section>(`/api/projects/${projectId}/sections/${sectionId}/content`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function listSectionRevisions(projectId: string, sectionId: string): Promise<SectionRevision[]> {
  return request<SectionRevision[]>(`/api/projects/${projectId}/sections/${sectionId}/revisions`);
}

export async function restoreSectionRevision(
  projectId: string,
  sectionId: string,
  revisionId: string,
): Promise<Section> {
  await getCsrfToken();
  return requestMutation<Section>(
    `/api/projects/${projectId}/sections/${sectionId}/revisions/${revisionId}/restore`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export async function listSessions(): Promise<SessionSummary[]> {
  return request<SessionSummary[]>("/api/auth/sessions");
}

export async function revokeSession(sessionId: string): Promise<void> {
  await getCsrfToken();
  await requestMutation<{ message: string }>(`/api/auth/sessions/${sessionId}`, { method: "DELETE" });
}

export type SourceStatus = "uploaded" | "processing" | "processed" | "failed";
export type PublicationType =
  | "article"
  | "book"
  | "book_chapter"
  | "thesis"
  | "memo"
  | "report"
  | "conference"
  | "website"
  | "other";

export interface Source {
  id: string;
  project_id: string;
  folder_id: string | null;
  original_filename: string;
  extension: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  status: SourceStatus;
  stage: string;
  progress: number;
  error_message: string | null;
  title: string | null;
  authors: string[];
  publication_year: number | null;
  doi: string | null;
  url: string | null;
  journal: string | null;
  volume: string | null;
  issue: string | null;
  pages: string | null;
  publisher: string | null;
  publication_type: PublicationType;
  abstract: string | null;
  keywords: string[];
  detected_language: string | null;
  page_count: number | null;
  imported_at: string;
  created_at: string;
  updated_at: string;
  tags: string[];
  duplicate_of: string | null;
  duplicate_reason: string | null;
  job_id: string | null;
}

export interface SourceFolder {
  id: string;
  project_id: string;
  name: string;
  created_at: string;
  source_count: number;
}

export interface SourceBlock {
  id: string;
  source_id: string;
  page_id: string | null;
  page_number: number;
  block_index: number;
  block_type: string;
  text: string;
  position_start: number;
  position_end: number;
  provenance_id: string;
}

export interface SourcePage {
  id: string;
  source_id: string;
  page_number: number;
  text: string;
  char_count: number;
  blocks: SourceBlock[];
}

export interface SourcePreview {
  source: Source;
  pages: SourcePage[];
  warnings: string[];
  ocr_used: boolean;
  sheets: string[];
}

export interface SourceSearchResult {
  source_id: string;
  source_title: string;
  original_filename: string;
  page_number: number;
  block_index: number;
  provenance_id: string;
  snippet: string;
  match_start: number;
  match_end: number;
}

export interface SourceList {
  items: Source[];
  total: number;
  limit: number;
  offset: number;
}

export interface SourceSearch {
  query: string;
  results: SourceSearchResult[];
  total: number;
}

export interface SourceMetadataInput {
  title?: string | null;
  authors?: string[];
  publication_year?: number | null;
  doi?: string | null;
  url?: string | null;
  journal?: string | null;
  volume?: string | null;
  issue?: string | null;
  pages?: string | null;
  publisher?: string | null;
  publication_type?: PublicationType;
  abstract?: string | null;
  keywords?: string[];
  folder_id?: string | null;
  tags?: string[];
}

function sourceQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const value = search.toString();
  return value ? `?${value}` : "";
}

export async function listSources(
  projectId: string,
  params: {
    q?: string;
    status?: SourceStatus;
    publication_type?: PublicationType;
    folder_id?: string;
    tag?: string;
    year?: number;
    sort?: string;
    order?: "asc" | "desc";
    limit?: number;
    offset?: number;
  } = {},
): Promise<SourceList> {
  return request<SourceList>(`/api/projects/${projectId}/sources${sourceQuery(params)}`);
}

export async function getSource(projectId: string, sourceId: string): Promise<Source> {
  return request<Source>(`/api/projects/${projectId}/sources/${sourceId}`);
}

export async function getSourcePreview(projectId: string, sourceId: string): Promise<SourcePreview> {
  return request<SourcePreview>(`/api/projects/${projectId}/sources/${sourceId}/preview`);
}

export async function updateSource(
  projectId: string,
  sourceId: string,
  input: SourceMetadataInput,
): Promise<Source> {
  await getCsrfToken();
  return requestMutation<Source>(`/api/projects/${projectId}/sources/${sourceId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function deleteSource(projectId: string, sourceId: string): Promise<void> {
  await getCsrfToken();
  await requestMutation<{ message: string }>(`/api/projects/${projectId}/sources/${sourceId}`, {
    method: "DELETE",
  });
}

export async function reprocessSource(projectId: string, sourceId: string): Promise<Source> {
  await getCsrfToken();
  return requestMutation<Source>(`/api/projects/${projectId}/sources/${sourceId}/reprocess`, {
    method: "POST",
  });
}

export async function searchSources(
  projectId: string,
  query: string,
  limit = 100,
): Promise<SourceSearch> {
  return request<SourceSearch>(`/api/projects/${projectId}/sources/search${sourceQuery({ q: query, limit })}`);
}

export async function listSourceFolders(projectId: string): Promise<SourceFolder[]> {
  return request<SourceFolder[]>(`/api/projects/${projectId}/sources/folders`);
}

export async function createSourceFolder(projectId: string, name: string): Promise<SourceFolder> {
  await getCsrfToken();
  return requestMutation<SourceFolder>(`/api/projects/${projectId}/sources/folders`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function deleteSourceFolder(projectId: string, folderId: string): Promise<void> {
  await getCsrfToken();
  await requestMutation<{ message: string }>(`/api/projects/${projectId}/sources/folders/${folderId}`, {
    method: "DELETE",
  });
}

export function sourceDownloadUrl(projectId: string, sourceId: string, preview = false): string {
  const suffix = preview ? "?preview=true" : "";
  return `${apiUrl}/api/projects/${projectId}/sources/${sourceId}/download${suffix}`;
}

export function uploadSource(
  projectId: string,
  file: File,
  options: {
    allowDuplicate?: boolean;
    folderId?: string;
    tags?: string[];
    onProgress?: (percent: number) => void;
    signal?: AbortSignal;
  } = {},
): Promise<Source> {
  return new Promise<Source>((resolve, reject) => {
    void getCsrfToken().then((token) => {
      const form = new FormData();
      form.append("file", file, file.name);
      form.append("allow_duplicate", String(options.allowDuplicate ?? false));
      if (options.folderId) form.append("folder_id", options.folderId);
      if (options.tags?.length) form.append("tags", options.tags.join(","));
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${apiUrl}/api/projects/${projectId}/sources/upload`);
      xhr.withCredentials = true;
      xhr.setRequestHeader("X-CSRF-Token", token);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) options.onProgress?.(Math.round((event.loaded / event.total) * 100));
      };
      xhr.onload = () => {
        let body: { source?: Source; detail?: unknown } = {};
        try {
          body = JSON.parse(xhr.responseText) as { source?: Source; detail?: unknown };
        } catch {
          body = {};
        }
        if (xhr.status >= 200 && xhr.status < 300 && body.source) {
          resolve(body.source);
        } else {
          const detail = body.detail;
          const message = typeof detail === "object" && detail !== null && "message" in detail
            ? String((detail as { message?: string }).message)
            : "Import impossible.";
          reject(new ApiError(xhr.status, message));
        }
      };
      xhr.onerror = () => reject(new ApiError(0, "Le téléchargement a échoué."));
      xhr.onabort = () => reject(new ApiError(0, "Import annulé."));
      if (options.signal) {
        if (options.signal.aborted) xhr.abort();
        else options.signal.addEventListener("abort", () => xhr.abort(), { once: true });
      }
      xhr.send(form);
    }).catch(reject);
  });
}


export type RagStrategy = "semantic" | "lexical" | "hybrid";
export type RagFusionMethod = "rrf" | "normalized";

export interface RagProvenance {
  project_id: string;
  chunk_id: string;
  rag_document_id: string;
  source_id: string;
  source_file_id: string | null;
  original_filename: string;
  source_title: string | null;
  source_authors: string[];
  source_year: number | null;
  page_number: number;
  block_start: number;
  block_end: number;
  chunk_index: number;
  provenance_id: string;
  character_start: number | null;
  character_end: number | null;
  heading_path: string[];
  block_types: string[];
  sentence_split: boolean;
  source_url: string;
  citation_marker?: string;
}

export interface RagSourceSummary {
  id: string;
  title: string | null;
  authors: string[];
  year: number | null;
  publication_type: string;
  journal: string | null;
  doi: string | null;
  original_filename: string;
  page_count: number | null;
  tags: string[];
  folder_id: string | null;
  file_id: string | null;
}

export interface RagSearchResult {
  chunk_id: string;
  text: string;
  score: number;
  vector_score: number | null;
  lexical_score: number | null;
  rerank_score: number | null;
  vector_rank: number | null;
  lexical_rank: number | null;
  token_count: number;
  source: RagSourceSummary;
  page: number;
  provenance: RagProvenance;
  citation_marker: string;
}

export interface RagSearchResponse {
  query: string;
  strategy: RagStrategy;
  fusion_method: RagFusionMethod | null;
  reranker: string;
  top_k: number;
  total_candidates: number;
  duration_ms: number;
  vector_hits: number;
  lexical_hits: number;
  results: RagSearchResult[];
}

export interface RagSearchFiltersInput {
  source_ids?: string[];
  publication_types?: string[];
  year_from?: number | null;
  year_to?: number | null;
  authors?: string[];
  page_from?: number | null;
  page_to?: number | null;
  folder_ids?: string[];
  tags?: string[];
}

export interface RagDocument {
  id: string;
  project_id: string;
  source_id: string;
  source_title: string | null;
  original_filename: string;
  status: "pending" | "chunking" | "embedding" | "indexed" | "failed";
  index_signature: string;
  embedding_provider: string;
  embedding_model: string;
  embedding_version: string;
  chunking_version: string;
  embedding_dimension: number;
  chunk_count: number;
  token_count: number;
  estimated_cost_usd: number;
  page_count: number | null;
  error_message: string | null;
  attempts: number;
  indexed_at: string | null;
  created_at: string;
  updated_at: string;
  needs_reindex: boolean;
}

export interface RagStats {
  documents_total: number;
  documents_indexed: number;
  documents_pending: number;
  chunks_total: number;
  tokens_total: number;
  estimated_cost_usd: number;
  embedding_provider: string;
  embedding_model: string;
  embedding_dimension: number;
  embedding_version: string;
  chunking_version: string;
  chunk_max_tokens: number;
  chunk_overlap_tokens: number;
  search_strategy: RagStrategy;
  fusion_method: RagFusionMethod;
  reranker: string;
}

export interface RagQueryHistoryEntry {
  id: string;
  query: string;
  strategy: string;
  fusion_method: string | null;
  top_k: number;
  result_count: number;
  semantic_hits: number;
  lexical_hits: number;
  duration_ms: number;
  created_at: string;
}

export async function ragSearch(
  projectId: string,
  input: {
    query: string;
    top_k?: number;
    strategy?: RagStrategy;
    fusion_method?: RagFusionMethod;
    filters?: RagSearchFiltersInput;
  },
): Promise<RagSearchResponse> {
  await getCsrfToken();
  return requestMutation<RagSearchResponse>(`/api/projects/${projectId}/rag/search`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function listRagDocuments(projectId: string): Promise<{ items: RagDocument[]; total: number }> {
  return request<{ items: RagDocument[]; total: number }>(`/api/projects/${projectId}/rag/documents`);
}

export async function getRagStats(projectId: string): Promise<RagStats> {
  return request<RagStats>(`/api/projects/${projectId}/rag/stats`);
}

export async function listRagQueryHistory(
  projectId: string,
  limit = 20,
): Promise<{ items: RagQueryHistoryEntry[] }> {
  return request<{ items: RagQueryHistoryEntry[] }>(`/api/projects/${projectId}/rag/queries?limit=${limit}`);
}

export async function indexSourceInRag(
  projectId: string,
  sourceId: string,
  force = false,
): Promise<{ message: string; queued: boolean }> {
  await getCsrfToken();
  return requestMutation<{ message: string; queued: boolean }>(
    `/api/projects/${projectId}/rag/sources/${sourceId}/index?force=${force ? "true" : "false"}`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export async function reindexSourceInRag(projectId: string, sourceId: string) {
  await getCsrfToken();
  return requestMutation<{ message: string; queued: boolean }>(
    `/api/projects/${projectId}/rag/sources/${sourceId}/reindex`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export async function deindexSourceInRag(projectId: string, sourceId: string) {
  await getCsrfToken();
  return requestMutation<{ message: string; queued: boolean }>(
    `/api/projects/${projectId}/rag/sources/${sourceId}/deindex`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export async function reindexProjectRag(projectId: string) {
  await getCsrfToken();
  return requestMutation<{ message: string; queued: boolean }>(
    `/api/projects/${projectId}/rag/reindex`,
    { method: "POST", body: JSON.stringify({}) },
  );
}


export type AssistantAnswerStatus = "completed" | "insufficient_sources" | "failed";

export interface AssistantCitation {
  position: number;
  citation_id: string;
  chunk_id: string | null;
  source_id: string | null;
  source_file_id: string | null;
  provenance_id: string | null;
  page: number;
  quote: string;
  rag_score: number;
  source_title: string | null;
  original_filename: string;
  authors: string[];
  publication_year: number | null;
  deep_link: string;
}

export interface AssistantMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  status: string;
  sequence: number;
  llm_provider: string | null;
  llm_model: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  cost_is_estimate: boolean;
  rag_duration_ms: number;
  llm_duration_ms: number;
  chunks_retrieved: number;
  error_category: string | null;
  grounding_note: string | null;
  created_at: string;
  citations: AssistantCitation[];
}

export interface AssistantConversationSummary {
  id: string;
  project_id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface AssistantConversation extends AssistantConversationSummary {
  summary: string | null;
  messages: AssistantMessage[];
}

export interface AssistantConversationList {
  items: AssistantConversationSummary[];
  total: number;
}

export interface AssistantAskResponse {
  status: AssistantAnswerStatus;
  message_id: string;
  conversation_id: string;
  question: string;
  answer: string | null;
  user_message: string;
  citations: AssistantCitation[];
  rejected_citations: string[];
  grounding_note: string | null;
  chunks_retrieved: number;
  reranked: boolean;
  llm_provider: string | null;
  llm_model: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  cost_is_estimate: boolean;
  rag_duration_ms: number;
  llm_duration_ms: number;
  created_at: string;
}

export interface AssistantConfig {
  provider: string;
  model: string;
  temperature: number;
  max_output_tokens: number;
  max_input_tokens: number;
  max_history_messages: number;
  top_k: number;
  min_context_score: number;
  rate_limit_enabled: boolean;
}

export interface AssistantUsage {
  questions_used_today: number;
  daily_tokens_used: number;
  daily_tokens_remaining: number;
  max_questions_per_minute: number;
  max_daily_tokens: number;
  rate_limit_enabled: boolean;
}

export async function listAssistantConversations(
  projectId: string,
): Promise<AssistantConversationList> {
  return request<AssistantConversationList>(`/api/projects/${projectId}/assistant/conversations`);
}

export async function createAssistantConversation(
  projectId: string,
  title?: string,
): Promise<AssistantConversation> {
  await getCsrfToken();
  return requestMutation<AssistantConversation>(`/api/projects/${projectId}/assistant/conversations`, {
    method: "POST",
    body: JSON.stringify({ title: title ?? null }),
  });
}

export async function getAssistantConversation(
  projectId: string,
  conversationId: string,
): Promise<AssistantConversation> {
  return request<AssistantConversation>(
    `/api/projects/${projectId}/assistant/conversations/${conversationId}`,
  );
}

export async function deleteAssistantConversation(
  projectId: string,
  conversationId: string,
): Promise<{ message: string; conversation_id: string }> {
  await getCsrfToken();
  return requestMutation<{ message: string; conversation_id: string }>(
    `/api/projects/${projectId}/assistant/conversations/${conversationId}`,
    { method: "DELETE" },
  );
}

export async function askAssistant(
  projectId: string,
  question: string,
  conversationId?: string,
): Promise<AssistantAskResponse> {
  await getCsrfToken();
  return requestMutation<AssistantAskResponse>(`/api/projects/${projectId}/assistant/ask`, {
    method: "POST",
    body: JSON.stringify({ question, conversation_id: conversationId ?? null }),
  });
}

export async function getAssistantConfig(projectId: string): Promise<AssistantConfig> {
  return request<AssistantConfig>(`/api/projects/${projectId}/assistant/config`);
}

export async function getAssistantUsage(projectId: string): Promise<AssistantUsage> {
  return request<AssistantUsage>(`/api/projects/${projectId}/assistant/usage`);
}


export type WritingAction =
  | "rephrase"
  | "correct"
  | "academic_style"
  | "summarize"
  | "expand"
  | "condense"
  | "translate"
  | "explain"
  | "transition"
  | "analyze_section"
  | "verify_claims"
  | "write_from_sources";

export type GenerationStatus = "completed" | "insufficient_sources" | "failed" | "discarded";

export interface WritingActionMeta {
  action: WritingAction;
  label: string;
  description: string;
  uses_sources: boolean;
  needs_selection: boolean;
  needs_full_section: boolean;
}

export interface WritingCatalog {
  actions: WritingActionMeta[];
  top_k: number;
  max_selection_chars: number;
  max_section_chars: number;
}

export interface WritingCitation {
  position: number;
  citation_id: string;
  chunk_id: string | null;
  source_id: string | null;
  source_file_id: string | null;
  provenance_id: string | null;
  page: number;
  quote: string;
  rag_score: number;
  source_title: string | null;
  original_filename: string;
  deep_link: string;
}

export interface WritingProposal {
  generation_id: string;
  action: WritingAction;
  status: GenerationStatus;
  proposed_text: string;
  user_message: string;
  citations: WritingCitation[];
  rejected_citations: string[];
  grounding_note: string | null;
  used_sources: boolean;
  chunks_retrieved: number;
  reranked: boolean;
  llm_provider: string | null;
  llm_model: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  cost_is_estimate: boolean;
  rag_duration_ms: number;
  llm_duration_ms: number;
  error_category: string | null;
  created_at: string;
}

export interface WritingGeneration {
  id: string;
  project_id: string;
  section_id: string | null;
  action: WritingAction;
  status: GenerationStatus;
  instruction: string;
  selection_excerpt: string;
  proposed_text: string;
  llm_provider: string | null;
  llm_model: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  cost_is_estimate: boolean;
  chunks_retrieved: number;
  used_sources: boolean;
  grounding_note: string | null;
  error_category: string | null;
  applied_at: string | null;
  created_at: string;
  citations: WritingCitation[];
}

export interface WritingGenerationList {
  items: WritingGeneration[];
  total: number;
}

export interface WritingRequestInput {
  action: WritingAction;
  instruction?: string;
  selection?: string;
  section_text?: string;
  previous_text?: string;
  section_id?: string | null;
  target_language?: string | null;
}

export async function getWritingCatalog(projectId: string): Promise<WritingCatalog> {
  return request<WritingCatalog>(`/api/projects/${projectId}/writing/actions`);
}

export async function generateWriting(
  projectId: string,
  input: WritingRequestInput,
): Promise<WritingProposal> {
  await getCsrfToken();
  return requestMutation<WritingProposal>(`/api/projects/${projectId}/writing/generate`, {
    method: "POST",
    body: JSON.stringify({
      action: input.action,
      instruction: input.instruction ?? "",
      selection: input.selection ?? "",
      section_text: input.section_text ?? "",
      previous_text: input.previous_text ?? "",
      section_id: input.section_id ?? null,
      target_language: input.target_language ?? null,
    }),
  });
}

export async function listWritingGenerations(
  projectId: string,
  sectionId?: string,
): Promise<WritingGenerationList> {
  const suffix = sectionId ? `?section_id=${sectionId}` : "";
  return request<WritingGenerationList>(`/api/projects/${projectId}/writing/generations${suffix}`);
}

export async function discardWritingGeneration(
  projectId: string,
  generationId: string,
): Promise<WritingGeneration> {
  await getCsrfToken();
  return requestMutation<WritingGeneration>(
    `/api/projects/${projectId}/writing/generations/${generationId}/discard`,
    { method: "POST", body: JSON.stringify({}) },
  );
}


export type ReferenceType =
  | "article"
  | "book"
  | "book_chapter"
  | "thesis"
  | "report"
  | "conference"
  | "webpage"
  | "dataset"
  | "patent"
  | "other";

export interface BibliographyAuthor {
  position: number;
  given_name: string | null;
  family_name: string;
  orcid: string | null;
}

export interface BibliographyCitationMatch {
  reference_id: string;
  citation_key: string;
  title: string | null;
  level: "exact" | "strong" | "possible";
  reason: string;
  title_similarity: number;
  shared_authors: string[];
}

export interface BibliographyDuplicateReport {
  has_duplicates: boolean;
  exact: BibliographyCitationMatch[];
  strong: BibliographyCitationMatch[];
  possible: BibliographyCitationMatch[];
}

export interface BibliographyReference {
  id: string;
  project_id: string;
  citation_key: string;
  reference_type: ReferenceType;
  entry_type: string | null;
  title: string | null;
  subtitle: string | null;
  authors: BibliographyAuthor[];
  publication_year: number | null;
  publication_month: string | null;
  publication_day: string | null;
  doi: string | null;
  doi_original: string | null;
  url: string | null;
  accessed_at: string | null;
  journal: string | null;
  volume: string | null;
  issue: string | null;
  pages: string | null;
  publisher: string | null;
  publisher_place: string | null;
  edition: string | null;
  isbn: string | null;
  issn: string | null;
  abstract: string | null;
  keywords: string[];
  language: string | null;
  notes: string | null;
  extra_fields: Record<string, string>;
  source_id: string | null;
  source_title: string | null;
  tags: string[];
  has_source: boolean;
  created_at: string;
  updated_at: string;
  missing_fields: string[];
}

export interface BibliographyList {
  items: BibliographyReference[];
  total: number;
  limit: number;
  offset: number;
}

export interface BibliographyStats {
  total: number;
  by_type: Record<string, number>;
  with_doi: number;
  with_source: number;
  with_url: number;
  with_abstract: number;
  by_year: Record<string, number>;
}

export interface BibliographyReferenceInput {
  citation_key?: string | null;
  reference_type?: ReferenceType;
  entry_type?: string | null;
  title?: string | null;
  subtitle?: string | null;
  authors?: { given_name?: string | null; family_name: string; orcid?: string | null }[];
  publication_year?: number | null;
  publication_month?: string | null;
  publication_day?: string | null;
  doi?: string | null;
  url?: string | null;
  accessed_at?: string | null;
  journal?: string | null;
  volume?: string | null;
  issue?: string | null;
  pages?: string | null;
  publisher?: string | null;
  publisher_place?: string | null;
  edition?: string | null;
  isbn?: string | null;
  issn?: string | null;
  abstract?: string | null;
  keywords?: string[];
  language?: string | null;
  notes?: string | null;
  source_id?: string | null;
  tags?: string[];
}

export interface BibliographyImportResult {
  imported: number;
  skipped: number;
  duplicates: number;
  errors: { message: string; citation_key: string | null }[];
  references: BibliographyReference[];
}

function bibliographyQuery(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "" && value !== null) search.set(key, String(value));
  });
  const value = search.toString();
  return value ? `?${value}` : "";
}

export async function listBibliography(
  projectId: string,
  params: {
    q?: string;
    reference_type?: ReferenceType;
    year?: number;
    author?: string;
    has_doi?: boolean;
    has_source?: boolean;
    tag?: string;
    sort?: string;
    order?: "asc" | "desc";
    limit?: number;
    offset?: number;
  } = {},
): Promise<BibliographyList> {
  return request<BibliographyList>(
    `/api/projects/${projectId}/bibliography${bibliographyQuery(params)}`,
  );
}

export async function searchBibliography(
  projectId: string,
  query: string,
): Promise<BibliographyList> {
  return listBibliography(projectId, { q: query, limit: 100 });
}

export async function getBibliographyStats(projectId: string): Promise<BibliographyStats> {
  return request<BibliographyStats>(`/api/projects/${projectId}/bibliography/stats`);
}

export async function getBibliographyReference(
  projectId: string,
  referenceId: string,
): Promise<BibliographyReference> {
  return request<BibliographyReference>(
    `/api/projects/${projectId}/bibliography/${referenceId}`,
  );
}

export async function createBibliographyReference(
  projectId: string,
  input: BibliographyReferenceInput,
): Promise<BibliographyReference> {
  await getCsrfToken();
  return requestMutation<BibliographyReference>(
    `/api/projects/${projectId}/bibliography`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export async function updateBibliographyReference(
  projectId: string,
  referenceId: string,
  input: Partial<BibliographyReferenceInput>,
): Promise<BibliographyReference> {
  await getCsrfToken();
  return requestMutation<BibliographyReference>(
    `/api/projects/${projectId}/bibliography/${referenceId}`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

export async function deleteBibliographyReference(
  projectId: string,
  referenceId: string,
): Promise<void> {
  await getCsrfToken();
  await requestMutation<{ message: string }>(
    `/api/projects/${projectId}/bibliography/${referenceId}`,
    { method: "DELETE" },
  );
}

export async function getBibliographyDuplicates(
  projectId: string,
  referenceId: string,
): Promise<BibliographyDuplicateReport> {
  return request<BibliographyDuplicateReport>(
    `/api/projects/${projectId}/bibliography/${referenceId}/duplicates`,
  );
}

export async function mergeBibliographyReference(
  projectId: string,
  duplicateId: string,
  keepId: string,
): Promise<BibliographyReference> {
  await getCsrfToken();
  return requestMutation<BibliographyReference>(
    `/api/projects/${projectId}/bibliography/${duplicateId}/merge`,
    { method: "POST", body: JSON.stringify({ keep_reference_id: keepId }) },
  );
}

export function exportBibliographyUrl(
  projectId: string,
  format: "bibtex" | "ris",
  referenceIds?: string[],
): string {
  const suffix = referenceIds?.length
    ? `?reference_ids=${referenceIds.join(",")}`
    : "";
  return `${apiUrl}/api/projects/${projectId}/bibliography/export/${format}${suffix}`;
}

export function importBibliographyUrl(
  projectId: string,
  format: "bibtex" | "ris",
): string {
  return `${apiUrl}/api/projects/${projectId}/bibliography/import/${format}`;
}

export async function importBibliographyFile(
  projectId: string,
  format: "bibtex" | "ris",
  file: File,
  skipDuplicates = true,
): Promise<BibliographyImportResult> {
  await getCsrfToken();
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("skip_duplicates", String(skipDuplicates));
  return requestFormData<BibliographyImportResult>(
    `/api/projects/${projectId}/bibliography/import/${format}`,
    form,
  );
}


/* ------------------------------------------------------------------ stage 10 */
/* Academic citations. The rendered text always comes from the server style engine, so the
   preview shown while picking a reference and the final document cannot disagree. */

export type LocatorType =
  | "page"
  | "pages"
  | "chapter"
  | "figure"
  | "table"
  | "section"
  | "other";

export type CitationMode = "parenthetical" | "narrative";

export interface CitationItemInput {
  reference_id: string;
  locator_type?: LocatorType | null;
  locator_value?: string | null;
  prefix?: string | null;
  suffix?: string | null;
}

export interface CitationItem extends CitationItemInput {
  citation_key: string | null;
  title: string | null;
  publication_year: number | null;
  author_labels: string[];
  position: number;
  is_available: boolean;
  number: number | null;
}

export interface Citation {
  id: string;
  project_id: string;
  section_id: string;
  node_id: string;
  citation_key: string;
  prefix: string | null;
  suffix: string | null;
  locator_type: LocatorType | null;
  locator_value: string | null;
  mode: CitationMode;
  position_in_section: number;
  items: CitationItem[];
  rendered_text: string;
  warnings: string[];
  is_orphaned: boolean;
  is_complete: boolean;
  is_stale_snapshot: boolean;
  snapshot_text: string | null;
  created_at: string;
  updated_at: string;
}

export interface CitationList {
  items: Citation[];
  total: number;
}

export interface RenderedCitation {
  node_id: string;
  citation_id: string | null;
  text: string;
  is_orphaned: boolean;
  warnings: string[];
  reference_ids: string[];
}

export interface SectionRender {
  section_id: string;
  style: string;
  style_label: string;
  citations: RenderedCitation[];
  orphaned: string[];
}

export interface CitationPreview {
  style: string;
  style_label: string;
  citation: string;
  bibliography_entry: string;
  warnings: string[];
  uses_style_engine: boolean;
}

export interface BibliographyEntry {
  reference_id: string;
  number: number | null;
  text: string;
  warnings: string[];
  citation_keys: string[];
  is_complete: boolean;
}

export interface UncitedReference {
  reference_id: string;
  citation_key: string;
  title: string | null;
  publication_year: number | null;
  reference_type: string;
}

export interface OrphanedCitation {
  citation_id: string;
  node_id: string;
  section_id: string;
  missing_reference_ids: string[];
  snapshot_text: string | null;
  snapshot_style: string | null;
  message: string;
}

export interface RenderedBibliography {
  style: string;
  style_label: string;
  entries: BibliographyEntry[];
  cited_count: number;
  uncited_count: number;
  uncited: UncitedReference[];
  orphaned_citations: OrphanedCitation[];
  incomplete_count: number;
  is_truncated: boolean;
}

export interface DocumentCitationCheck {
  section_id: string;
  style: string;
  citations: RenderedCitation[];
  unregistered_node_ids: string[];
  stale_citation_ids: string[];
  orphaned_node_ids: string[];
  synced: number;
}

export interface CitationStyleEntry {
  name: string;
  label: string;
  uses_numbers: boolean;
  date_missing: string;
}

export async function listCitations(
  projectId: string,
  sectionId?: string,
): Promise<CitationList> {
  const query = sectionId ? `?section_id=${sectionId}` : "";
  return request<CitationList>(`/api/projects/${projectId}/citations${query}`);
}

export async function getCitation(
  projectId: string,
  citationId: string,
): Promise<Citation> {
  return request<Citation>(`/api/projects/${projectId}/citations/${citationId}`);
}

export async function getRenderedCitations(
  projectId: string,
  sectionId?: string,
  style?: string,
): Promise<SectionRender> {
  const params = new URLSearchParams();
  if (sectionId) params.set("section_id", sectionId);
  if (style) params.set("style", style);
  const query = params.toString();
  return request<SectionRender>(
    `/api/projects/${projectId}/citations/rendered${query ? `?${query}` : ""}`,
  );
}

export async function getCitationStyles(projectId: string): Promise<CitationStyleEntry[]> {
  return request<CitationStyleEntry[]>(`/api/projects/${projectId}/citations/styles`);
}

/** Render a citation that is not stored yet, with the very same engine. */
export async function previewCitation(
  projectId: string,
  input: {
    style?: string;
    items: CitationItemInput[];
    prefix?: string | null;
    suffix?: string | null;
    mode?: CitationMode;
  },
): Promise<CitationPreview> {
  await getCsrfToken();
  return requestMutation<CitationPreview>(`/api/projects/${projectId}/citations/preview`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function upsertCitation(
  projectId: string,
  input: {
    section_id: string;
    node_id: string;
    items: CitationItemInput[];
    prefix?: string | null;
    suffix?: string | null;
    locator_type?: LocatorType | null;
    locator_value?: string | null;
    mode?: CitationMode;
    position_in_section?: number;
  },
): Promise<Citation> {
  await getCsrfToken();
  return requestMutation<Citation>(`/api/projects/${projectId}/citations`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function patchCitation(
  projectId: string,
  citationId: string,
  input: {
    items?: CitationItemInput[];
    prefix?: string | null;
    suffix?: string | null;
    locator_type?: LocatorType | null;
    locator_value?: string | null;
    mode?: CitationMode;
    position_in_section?: number;
    remove_reference_id?: string;
  },
): Promise<Citation> {
  await getCsrfToken();
  return requestMutation<Citation>(
    `/api/projects/${projectId}/citations/${citationId}`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

export async function deleteCitation(
  projectId: string,
  citationId: string,
): Promise<void> {
  await getCsrfToken();
  await requestMutation<{ message: string }>(
    `/api/projects/${projectId}/citations/${citationId}`,
    { method: "DELETE" },
  );
}

export async function detachCitationReference(
  projectId: string,
  citationId: string,
  referenceId: string,
): Promise<Citation> {
  await getCsrfToken();
  return requestMutation<Citation>(
    `/api/projects/${projectId}/citations/${citationId}/detach-reference?reference_id=${referenceId}`,
    { method: "POST" },
  );
}

/** Register the citations of a saved document and report what needs repair. */
export async function reconcileCitations(
  projectId: string,
  sectionId: string,
  content: unknown,
): Promise<DocumentCitationCheck> {
  await getCsrfToken();
  return requestMutation<DocumentCitationCheck>(
    `/api/projects/${projectId}/citations/reconcile?section_id=${sectionId}`,
    { method: "POST", body: JSON.stringify(content) },
  );
}

export async function getRenderedBibliography(
  projectId: string,
  style?: string,
): Promise<RenderedBibliography> {
  const query = style ? `?style=${style}` : "";
  return request<RenderedBibliography>(
    `/api/projects/${projectId}/bibliography/rendered${query}`,
  );
}

export async function refreshBibliography(
  projectId: string,
  style?: string,
): Promise<RenderedBibliography> {
  await getCsrfToken();
  const query = style ? `?style=${style}` : "";
  return requestMutation<RenderedBibliography>(
    `/api/projects/${projectId}/bibliography/refresh${query}`,
    { method: "POST" },
  );
}


/* ------------------------------------------------------------------ stage 11 */
/* Academic export. The file is produced by the server from the same citation engine as the
   editor, so the exported memoir cannot disagree with what the author sees. */

export type ExportFormat = "pdf" | "docx";

export interface ExportOptions {
  page_size?: "a4" | "letter";
  orientation?: "portrait" | "landscape";
  margin_top?: number;
  margin_bottom?: number;
  margin_left?: number;
  margin_right?: number;
  font_family?: "times" | "helvetica" | "courier";
  font_size?: number;
  line_spacing?: number;
  first_line_indent?: number;
  paragraph_alignment?: "left" | "center" | "right" | "justify";
  paragraph_space_after?: number;
  include_cover?: boolean;
  include_toc?: boolean;
  include_list_of_figures?: boolean;
  include_list_of_tables?: boolean;
  include_bibliography?: boolean;
  include_annexes?: boolean;
  include_page_numbers?: boolean;
  roman_front_matter?: boolean;
  show_running_head?: boolean;
  header_text?: string | null;
  footer_text?: string | null;
  number_headings?: boolean;
  number_figures?: boolean;
  number_tables?: boolean;
  number_equations?: boolean;
  embed_remote_images?: boolean;
  bibliography_heading?: string;
  toc_heading?: string;
  list_of_figures_heading?: string;
  list_of_tables_heading?: string;
}

export interface ExportFormatInfo {
  format: ExportFormat;
  label: string;
  extension: string;
  media_type: string;
}

export interface ExportCatalogue {
  formats: ExportFormatInfo[];
  page_sizes: string[];
  fonts: { name: string; label: string }[];
  defaults: Record<string, unknown> & {
    limits?: { max_sections?: number; max_blocks?: number; max_output_bytes?: number };
  };
}

export interface ExportPreview {
  format: ExportFormat;
  style: string;
  style_label: string;
  project_title: string;
  section_count: number;
  section_titles: string[];
  figure_count: number;
  table_count: number;
  citation_count: number;
  bibliography_entries: number;
  uncited_count: number;
  orphan_count: number;
  annex_count: number;
  warnings: string[];
  has_cover: boolean;
  has_toc: boolean;
}

export interface ExportRecord {
  id: string;
  project_id: string;
  format: ExportFormat;
  file_name: string;
  size_bytes: number;
  style: string | null;
  style_label: string | null;
  section_count: number;
  figure_count: number;
  table_count: number;
  citation_count: number;
  uncited_count: number;
  orphan_count: number;
  warnings: string[];
  duration_ms: number | null;
  created_at: string;
}

export interface ExportList {
  items: ExportRecord[];
  total: number;
}

export async function getExportCatalogue(projectId: string): Promise<ExportCatalogue> {
  return request<ExportCatalogue>(`/api/projects/${projectId}/exports/formats`);
}

export async function previewExport(
  projectId: string,
  format: ExportFormat,
  options: ExportOptions = {},
): Promise<ExportPreview> {
  await getCsrfToken();
  return requestMutation<ExportPreview>(`/api/projects/${projectId}/exports/preview`, {
    method: "POST",
    body: JSON.stringify({ format, options }),
  });
}

export async function listExports(
  projectId: string,
  limit = 10,
): Promise<ExportList> {
  return request<ExportList>(`/api/projects/${projectId}/exports?limit=${limit}`);
}

/** Download an export. The file is produced by the server and never assembled in the browser. */
export async function downloadExport(
  projectId: string,
  format: ExportFormat,
  options: ExportOptions = {},
): Promise<{ fileName: string; size: number }> {
  await getCsrfToken();
  const response = await fetch(`${apiUrl}/api/projects/${projectId}/exports/${format}`, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": readCookie(csrfCookieName) ?? "",
    },
    body: JSON.stringify(options),
  });
  if (!response.ok) {
    let message = "Export impossible.";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Keep the generic message when the body is not JSON.
    }
    throw new ApiError(response.status, message);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  const fileName = match?.[1] ?? `memoire.${format}`;
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  return { fileName, size: blob.size };
}


/* ------------------------------------------------------------------ stage 12 */
/* Academic audit. The report is computed on the server by deterministic checks: it never
   writes to the memoir and never asks a language model what is wrong with it. */

export type AuditSeverity = "blocker" | "warning" | "info";

export interface AuditFinding {
  code: string;
  severity: AuditSeverity;
  severity_label: string;
  title: string;
  detail: string;
  location_kind: string | null;
  location_ref: string | null;
  location_label: string | null;
  remedy: string | null;
  count: number;
  meta: Record<string, unknown>;
}

export interface AuditCheck {
  code: string;
  finding_count: number;
  skipped_reason: string | null;
}

export interface AuditReadiness {
  level: "aucun_bloquant" | "corrections_requises" | "reprise_necessaire";
  label: string;
  detail: string;
}

export interface AuditObservation {
  code: string;
  label: string;
  detail: string;
}

export interface DefenceChecklistItem {
  priority: number;
  category: string;
  question: string;
  evidence: string | null;
}

export interface SectionStat {
  section_id: string;
  title: string;
  level: number;
  word_count: number;
  citation_count: number;
  figure_count: number;
  table_count: number;
  status: string;
  citation_density: number | null;
  read_minutes: number;
}

export interface ThesisStats {
  project_id: string;
  title: string;
  section_count: number;
  chapter_count: number;
  subsection_count: number;
  empty_section_count: number;
  completed_section_count: number;
  word_count: number;
  character_count: number;
  read_minutes: number;
  longest_section: string | null;
  longest_section_words: number;
  average_section_words: number;
  citation_count: number;
  distinct_cited_references: number;
  orphan_citation_count: number;
  pending_citation_count: number;
  narrative_citation_count: number;
  reference_count: number;
  uncited_reference_count: number;
  references_with_doi: number;
  references_with_url: number;
  reference_type_counts: Record<string, number>;
  reference_year_span: number[] | null;
  most_cited_references: { reference_id: string; citation_key: string | null; title: string | null; count: number }[];
  citation_density: number | null;
  bibliography_style: string;
  dangling_citation_references: number;
  source_count: number;
  indexed_source_count: number;
  source_page_count: number;
  source_block_count: number;
  figure_count: number;
  table_count: number;
  equation_count: number;
  sections: SectionStat[];
}

export interface AuditReport {
  project_id: string;
  project_title: string;
  generated_at: string;
  readiness: AuditReadiness;
  summary: {
    blockers: number;
    warnings: number;
    info: number;
    checks_run: number;
    checks_inconclusive: number;
    labels: Record<string, string>;
  };
  findings: AuditFinding[];
  findings_by_code: Record<string, number>;
  checks: AuditCheck[];
  statistics: ThesisStats;
  observations: AuditObservation[];
  defence_checklist: DefenceChecklistItem[];
  disclaimer: string;
}

export interface AuditTrace {
  id: string;
  project_id: string;
  readiness: AuditReadiness["level"];
  blocker_count: number;
  warning_count: number;
  info_count: number;
  checks_run: number;
  checks_inconclusive: number;
  word_count: number;
  citation_count: number;
  reference_count: number;
  findings: Record<string, unknown>[];
  duration_ms: number | null;
  created_at: string;
}

export interface AuditTraceList {
  items: AuditTrace[];
  total: number;
  blocker_trend: number | null;
}

export async function getAuditReport(projectId: string): Promise<AuditReport> {
  return request<AuditReport>(`/api/projects/${projectId}/audit`);
}

export async function runAudit(
  projectId: string,
  storeTrace = false,
): Promise<{ report: AuditReport; trace_id: string | null; duration_ms: number }> {
  await getCsrfToken();
  return requestMutation<{
    report: AuditReport;
    trace_id: string | null;
    duration_ms: number;
  }>(`/api/projects/${projectId}/audit/run`, {
    method: "POST",
    body: JSON.stringify({ store_trace: storeTrace }),
  });
}

export async function listAuditTraces(projectId: string): Promise<AuditTraceList> {
  return request<AuditTraceList>(`/api/projects/${projectId}/audit/traces`);
}

export async function deleteAuditTrace(
  projectId: string,
  traceId: string,
): Promise<void> {
  await getCsrfToken();
  await requestMutation<{ message: string }>(
    `/api/projects/${projectId}/audit/traces/${traceId}`,
    { method: "DELETE" },
  );
}


/* ------------------------------------------------------------------ stage 13 */
/* Platform administration and observability. Administration manages accounts; it is not a
   way to read a memoir, and the interface never offers one. */

export interface AdminUser {
  user_id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  is_admin: boolean;
  is_suspended: boolean;
  suspended_at: string | null;
  suspended_reason: string | null;
  created_at: string | null;
  last_login_at: string | null;
  project_count: number;
  owned_project_count: number;
}

export interface AdminUserList {
  items: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

export interface PlatformStats {
  users: number;
  suspended_users: number;
  administrators: number;
  projects: number;
  archived_projects: number;
  sources: number;
  citations: number;
  exports: number;
  audits: number;
  blockers_open: number;
}

export interface AdminAction {
  id: string;
  actor_id: string | null;
  target_user_id: string | null;
  action: string;
  target: string | null;
  reason: string | null;
  outcome: string;
  created_at: string | null;
}

export interface ObservabilitySnapshot {
  version: string;
  scope: string;
  warning: string;
  started_at: string;
  uptime_seconds: number;
  requests: {
    total: number;
    by_route: Record<string, number>;
    errors_5xx: number;
    rate_limited: number;
  };
  latency_ms: { count: number; p50?: number; p95?: number; p99?: number; max?: number };
  by_route: Record<string, { count: number; p50?: number; p95?: number }>;
  security_events: Record<string, number>;
  exports: Record<string, number>;
  llm: { calls: number; tokens: number };
  rag_queries: number;
}

export interface SecurityEvent {
  id: string;
  kind: string;
  user_id: string | null;
  project_id: string | null;
  resource: string | null;
  outcome: string;
  detail: string | null;
  path: string | null;
  created_at: string | null;
}

export async function listAdminUsers(
  query?: string,
  onlySuspended = false,
): Promise<AdminUserList> {
  const params = new URLSearchParams();
  if (query) params.set("query", query);
  if (onlySuspended) params.set("only_suspended", "true");
  const suffix = params.toString();
  return request<AdminUserList>(`/api/admin/users${suffix ? `?${suffix}` : ""}`);
}

export async function getPlatformStats(): Promise<PlatformStats> {
  return request<PlatformStats>("/api/admin/stats");
}

export async function setUserSuspension(
  userId: string,
  suspended: boolean,
  reason?: string,
): Promise<AdminUser> {
  await getCsrfToken();
  const params = new URLSearchParams({ suspended: String(suspended) });
  if (reason) params.set("reason", reason);
  return requestMutation<AdminUser>(
    `/api/admin/users/${userId}/suspension?${params.toString()}`,
    { method: "POST" },
  );
}

export async function setUserAdministrator(
  userId: string,
  isAdmin: boolean,
): Promise<AdminUser> {
  await getCsrfToken();
  return requestMutation<AdminUser>(
    `/api/admin/users/${userId}/administrator?is_admin=${isAdmin}`,
    { method: "POST" },
  );
}

export async function listAdminActions(): Promise<{ items: AdminAction[] }> {
  return request<{ items: AdminAction[] }>("/api/admin/admin-actions");
}

export async function getMetrics(): Promise<ObservabilitySnapshot> {
  return request<ObservabilitySnapshot>("/api/observability/metrics");
}

export async function getHealthDetails(): Promise<{
  status: string;
  dependencies: Record<string, string>;
  version: string;
  environment: string;
}> {
  return request("/api/observability/health/details");
}

export async function listSecurityEvents(
  kind?: string,
  sinceHours = 168,
): Promise<{ items: SecurityEvent[]; total: number }> {
  const params = new URLSearchParams({ since_hours: String(sinceHours) });
  if (kind) params.set("kind", kind);
  return request<{ items: SecurityEvent[]; total: number }>(
    `/api/observability/security-events?${params.toString()}`,
  );
}
