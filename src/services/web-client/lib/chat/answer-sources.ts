import type { AnswerSource } from "@/lib/types";

export const KNOWLEDGE_STORE_DOCUMENT_PARAM = "doc";

const UNTITLED_SOURCE = "Untitled document";

function textOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function pageOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function answerSourcesOf(value: unknown): AnswerSource[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value
    .filter(
      (entry): entry is Record<string, unknown> => entry !== null && typeof entry === "object"
    )
    .map((entry) => ({
      doc_id: textOrNull(entry.doc_id),
      chunk_id: textOrNull(entry.chunk_id),
      title: textOrNull(entry.title),
      page: pageOrNull(entry.page),
    }));
}

export function sourceLabel(source: AnswerSource): string {
  const title = source.title ?? UNTITLED_SOURCE;
  return source.page !== null ? `${title}, page ${source.page}` : title;
}

export function knowledgeStoreDocumentHref(source: AnswerSource): string | null {
  if (!source.doc_id) return null;
  return `/knowledge-store?${KNOWLEDGE_STORE_DOCUMENT_PARAM}=${encodeURIComponent(source.doc_id)}`;
}

export function distinctSources(sources: AnswerSource[]): AnswerSource[] {
  const seen = new Set<string>();
  return sources.filter((source) => {
    const key = `${source.doc_id ?? ""}|${sourceLabel(source)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function requestedDocumentId(search: string): string | null {
  return textOrNull(new URLSearchParams(search).get(KNOWLEDGE_STORE_DOCUMENT_PARAM));
}
