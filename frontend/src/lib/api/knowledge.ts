import { apiFetch } from "./client";

export type KnowledgeDocument = {
  id: string;
  title: string;
  kind: "text" | "file";
  source_name: string | null;
  content_type: string;
  size_bytes: number;
  tags: string[];
  chunk_count: number;
  preview: string;
  created_by_label: string;
  created_at: string;
  updated_at: string;
};

export type KnowledgeDocumentDetail = KnowledgeDocument & { text: string };

export type KnowledgeHit = {
  document_id: string;
  title: string;
  position: number;
  text: string;
  score: number;
};

export type KnowledgeSearch = { query: string; hits: KnowledgeHit[]; documents_total: number };

export type KnowledgeFormats = { extensions: string[]; max_file_mb: number; max_text_chars: number };

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

export function describeKind(document: Pick<KnowledgeDocument, "kind" | "source_name">): string {
  if (document.kind === "text") return "текст";
  const extension = document.source_name?.split(".").pop()?.toLowerCase();
  return extension ? `файл ${extension}` : "файл";
}

/** Список тегов из строки «через запятую» — как его понимает бэкенд. */
export function parseTags(value: string): string[] {
  const seen: string[] = [];
  for (const raw of value.split(",")) {
    const tag = raw.trim().toLowerCase().slice(0, 40);
    if (tag && !seen.includes(tag)) seen.push(tag);
  }
  return seen.slice(0, 20);
}

export const knowledgeApi = {
  list: () => apiFetch<KnowledgeDocument[]>("/knowledge"),
  formats: () => apiFetch<KnowledgeFormats>("/knowledge/formats"),
  get: (id: string) => apiFetch<KnowledgeDocumentDetail>(`/knowledge/${id}`),
  createText: (body: { title: string; text: string; tags?: string[] }) =>
    apiFetch<KnowledgeDocument>("/knowledge", { method: "POST", body }),
  upload: (file: File, options: { title?: string; tags?: string } = {}) => {
    const form = new FormData();
    form.append("file", file, file.name);
    if (options.title) form.append("title", options.title);
    if (options.tags) form.append("tags", options.tags);
    return apiFetch<KnowledgeDocument>("/knowledge/upload", { method: "POST", body: form });
  },
  update: (id: string, body: { title?: string; text?: string; tags?: string[] }) =>
    apiFetch<KnowledgeDocumentDetail>(`/knowledge/${id}`, { method: "PATCH", body }),
  remove: (id: string) => apiFetch<void>(`/knowledge/${id}`, { method: "DELETE" }),
  search: (query: string, limit = 5) =>
    apiFetch<KnowledgeSearch>(
      `/knowledge/search?q=${encodeURIComponent(query)}&limit=${limit}`,
    ),
};
