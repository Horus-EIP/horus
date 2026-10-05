import { config } from "@/utils/config";

export interface KnowledgeStoreDocument {
  id: string;
  title: string;
  date?: string;
  size?: number;
  summary?: string;
  excerpt?: string;
  category?: string;
  document_type?: string;
  confidence_score?: number;
}

export interface KSResponse<T> {
  ok: boolean;
  data?: T;
  error?: string;
}

export interface KnowledgeStoreCategory {
  category: string;
  count: number;
}

export interface SmartSearchRequest {
  query: string;
  n_results?: number;
  categories?: string[];
  entities?: string[];
  min_confidence?: number;
  entity_type?: string;
}

export interface SmartSearchMetadata {
  title?: string;
  date?: string;
  size?: number;
  auto_category?: string;
  auto_type?: string;
  auto_summary?: string;
  confidence_score?: number;
  [key: string]: unknown;
}

export interface SmartSearchHit {
  content: string;
  metadata: SmartSearchMetadata;
  distance: number | null;
}

interface SmartSearchResponse {
  results?: {
    documents?: string[];
    metadatas?: (SmartSearchMetadata | null)[];
    distances?: number[];
  };
}

function ksUrl(path: string): string {
  const base = config.knowledgeStoreUrl.replace(/\/$/, "");
  return `${base}${config.knowledgeStoreApiPrefix}${path}`;
}

export const knowledgeStoreApi = {
  async listDocuments(): Promise<KSResponse<KnowledgeStoreDocument[]>> {
    try {
      const res = await fetch(ksUrl("/file"), { method: "GET" });
      if (!res.ok) {
        return { ok: false, error: `Knowledge store responded ${res.status}` };
      }
      const json = (await res.json()) as { documents?: KnowledgeStoreDocument[] };
      return { ok: true, data: json.documents ?? [] };
    } catch (err) {
      return {
        ok: false,
        error: err instanceof Error ? err.message : "Network error",
      };
    }
  },

  async smartSearch(
    request: SmartSearchRequest
  ): Promise<KSResponse<SmartSearchHit[]>> {
    try {
      const res = await fetch(ksUrl("/smart-search"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      if (res.status === 404) {
        return { ok: true, data: [] };
      }
      if (!res.ok) {
        return { ok: false, error: `Knowledge store responded ${res.status}` };
      }
      const json = (await res.json()) as SmartSearchResponse;
      const metadatas = json.results?.metadatas ?? [];
      const distances = json.results?.distances ?? [];
      return {
        ok: true,
        data: (json.results?.documents ?? []).map((content, index) => ({
          content,
          metadata: metadatas[index] ?? {},
          distance: distances[index] ?? null,
        })),
      };
    } catch (err) {
      return {
        ok: false,
        error: err instanceof Error ? err.message : "Network error",
      };
    }
  },

  async getCategories(): Promise<KSResponse<KnowledgeStoreCategory[]>> {
    try {
      const res = await fetch(ksUrl("/categories"), { method: "GET" });
      if (!res.ok) {
        return { ok: false, error: `Knowledge store responded ${res.status}` };
      }
      const json = (await res.json()) as { categories?: KnowledgeStoreCategory[] };
      return { ok: true, data: json.categories ?? [] };
    } catch (err) {
      return {
        ok: false,
        error: err instanceof Error ? err.message : "Network error",
      };
    }
  },

  /** Upload one or more files. Returns the per-file results from the KS. */
  async uploadDocuments(
    files: File[]
  ): Promise<
    KSResponse<{ filename: string; doc_id?: string; error?: string }[]>
  > {
    return knowledgeStoreApi.uploadDocumentsWithProgress(files);
  },

  /** Upload one or more files with real-time progress callbacks.
   *
   * Uses XHR (not fetch) because fetch can't report upload-side progress
   * portably. Phase transitions reported on the callback:
   *   - "uploading" while bytes travel to the server
   *   - "processing" after upload completes but before KS responds
   *     (server is extracting text + running analysis; no real ETA here)
   *   - "done" once the response is parsed; "error" on any failure
   */
  uploadDocumentsWithProgress(
    files: File[],
    onProgress?: (snapshot: UploadProgress) => void
  ): Promise<
    KSResponse<{ filename: string; doc_id?: string; error?: string }[]>
  > {
    if (!files.length) {
      return Promise.resolve({ ok: true, data: [] });
    }
    const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
    const form = new FormData();
    for (const f of files) form.append("files", f);

    const startedAt = performance.now();
    const emit = (s: Omit<UploadProgress, "totalBytes">) =>
      onProgress?.({ ...s, totalBytes });

    const targetUrl = ksUrl("/file");
    return new Promise((resolve) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", targetUrl);
      // Don't set responseType to "json" — when the server returns a body
      // the browser can't parse for any reason (e.g. server error page,
      // unexpected content-type), xhr.response goes silently to null and the
      // upload looks like a no-op. Read responseText and parse manually so
      // we can surface the real reason on failure.

      xhr.upload.addEventListener("progress", (event) => {
        if (!event.lengthComputable) return;
        const elapsed = (performance.now() - startedAt) / 1000;
        const bps = elapsed > 0 ? event.loaded / elapsed : 0;
        const remainingBytes = Math.max(0, event.total - event.loaded);
        const etaSeconds = bps > 0 ? remainingBytes / bps : null;
        emit({
          phase: "uploading",
          loadedBytes: event.loaded,
          bytesPerSecond: bps,
          etaSeconds,
        });
      });

      // Browser has finished sending the request body; we're now waiting for
      // KS to extract + analyse. No upload-side progress past this point.
      xhr.upload.addEventListener("load", () => {
        emit({
          phase: "processing",
          loadedBytes: totalBytes,
          bytesPerSecond: 0,
          etaSeconds: null,
        });
      });

      xhr.addEventListener("load", () => {
        const rawBody = xhr.responseText || "";
        if (xhr.status < 200 || xhr.status >= 300) {
          const snippet = rawBody.slice(0, 300);
          // Log to the browser console so the dev tools show the full URL +
          // server reply that actually came back. The toast only gets a
          // short summary.
          console.error(
            "[knowledge-store] upload failed",
            { url: targetUrl, status: xhr.status, body: rawBody }
          );
          emit({
            phase: "error",
            loadedBytes: totalBytes,
            bytesPerSecond: 0,
            etaSeconds: null,
          });
          resolve({
            ok: false,
            error: `KS responded ${xhr.status}: ${snippet || xhr.statusText}`,
          });
          return;
        }
        let body: { filename: string; doc_id?: string; error?: string }[] = [];
        try {
          body = rawBody ? JSON.parse(rawBody) : [];
        } catch (parseErr) {
          console.error(
            "[knowledge-store] upload succeeded but response wasn't JSON",
            { url: targetUrl, body: rawBody, parseErr }
          );
        }
        emit({
          phase: "done",
          loadedBytes: totalBytes,
          bytesPerSecond: 0,
          etaSeconds: 0,
        });
        resolve({ ok: true, data: body });
      });

      xhr.addEventListener("error", () => {
        // Browsers deliberately hide CORS / DNS / refused-connection details
        // from JS for security. The console will have the specifics; we
        // surface a hint of the most common causes.
        console.error("[knowledge-store] xhr.onerror", {
          url: targetUrl,
          readyState: xhr.readyState,
          status: xhr.status,
        });
        emit({
          phase: "error",
          loadedBytes: 0,
          bytesPerSecond: 0,
          etaSeconds: null,
        });
        resolve({
          ok: false,
          error: `Could not reach ${targetUrl}. Open the browser DevTools Network tab for the real reason (likely CORS, connection refused, or a stale bundle — try a hard reload).`,
        });
      });

      xhr.addEventListener("abort", () => {
        emit({
          phase: "error",
          loadedBytes: 0,
          bytesPerSecond: 0,
          etaSeconds: null,
        });
        resolve({ ok: false, error: "Upload aborted" });
      });

      xhr.addEventListener("timeout", () => {
        emit({
          phase: "error",
          loadedBytes: 0,
          bytesPerSecond: 0,
          etaSeconds: null,
        });
        resolve({
          ok: false,
          error: `KS request timed out after ${xhr.timeout / 1000}s.`,
        });
      });

      // KS extracts + analyses on upload, which can take a few seconds per MB.
      // 5 minutes is generous; tighten in your own deployment if needed.
      xhr.timeout = 5 * 60 * 1000;
      xhr.send(form);
    });
  },
};

export type UploadPhase = "uploading" | "processing" | "done" | "error";

export interface UploadProgress {
  phase: UploadPhase;
  loadedBytes: number;
  totalBytes: number;
  bytesPerSecond: number;
  /** ``null`` when throughput is unknown; ``0`` once the upload finishes. */
  etaSeconds: number | null;
}

export function formatEta(seconds: number | null | undefined): string {
  if (seconds == null) return "estimating…";
  if (seconds <= 1) return "almost done";
  if (seconds < 60) return `${Math.round(seconds)}s left`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s ? `${m}m ${s}s left` : `${m}m left`;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** Read a File as base64 (no data-URL prefix). Used for the "don't save to KS" path. */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
