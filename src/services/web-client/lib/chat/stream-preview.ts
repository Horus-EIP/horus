export interface StreamPreview {
  subtaskId: string;
  text: string;
}

export type StreamPreviews = Record<string, StreamPreview>;

export function appendStreamChunk(
  previews: StreamPreviews,
  taskId: string,
  subtaskId: string,
  chunk: string
): StreamPreviews {
  const current = previews[taskId];
  const text =
    current && current.subtaskId === subtaskId ? current.text + chunk : chunk;
  return { ...previews, [taskId]: { subtaskId, text } };
}
