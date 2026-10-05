export interface StreamPreview {
  subtaskId: string;
  text: string;
}

export type StreamPreviews = Record<string, StreamPreview>;

const FIRST_CHUNK_INDEX = 0;

export function appendStreamChunk(
  previews: StreamPreviews,
  taskId: string,
  subtaskId: string,
  chunk: string,
  index?: number
): StreamPreviews {
  const current = previews[taskId];
  const continues =
    current !== undefined && current.subtaskId === subtaskId && index !== FIRST_CHUNK_INDEX;
  const text = continues ? current.text + chunk : chunk;
  return { ...previews, [taskId]: { subtaskId, text } };
}

export function dropStreamPreview(previews: StreamPreviews, taskId: string): StreamPreviews {
  if (!(taskId in previews)) return previews;
  const rest = { ...previews };
  delete rest[taskId];
  return rest;
}
