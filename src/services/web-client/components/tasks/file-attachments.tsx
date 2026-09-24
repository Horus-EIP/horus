'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Group,
  Modal,
  MultiSelect,
  Stack,
  Tabs,
  Text,
} from '@mantine/core';
import {
  IconCloudUpload,
  IconDatabase,
  IconPaperclip,
  IconUpload,
  IconX,
} from '@tabler/icons-react';
import { useDropzone } from 'react-dropzone';
import {
  fileToBase64,
  knowledgeStoreApi,
  type KnowledgeStoreDocument,
  type UploadProgress as UploadProgressData,
} from '@/lib/knowledge-store/api';
import { UploadProgress } from '@/components/knowledge-store/upload-progress';
import type {
  InlineTaskFile,
  KnowledgeStoreFileRef,
} from '@/lib/types';

const MAX_INLINE_FILE_BYTES = 2 * 1024 * 1024;

export interface FileAttachmentsValue {
  attached: KnowledgeStoreFileRef[];
  inline: InlineTaskFile[];
}

interface FileAttachmentsProps {
  value: FileAttachmentsValue;
  onChange: (next: FileAttachmentsValue) => void;
  /** Show a compact one-line button (chat) vs. the full picker (tasks/new). */
  compact?: boolean;
  onError?: (msg: string) => void;
}

type PendingUpload = { file: File; size: number };

export function FileAttachments({
  value,
  onChange,
  compact = false,
  onError,
}: FileAttachmentsProps) {
  const [docs, setDocs] = useState<KnowledgeStoreDocument[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [picker, setPicker] = useState(compact ? false : true);
  const [saveModalOpen, setSaveModalOpen] = useState(false);
  const [pendingUploads, setPendingUploads] = useState<PendingUpload[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] =
    useState<UploadProgressData | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const reportError = useRef(onError);
  reportError.current = onError;

  const refreshDocs = useCallback(async () => {
    setDocsLoading(true);
    const result = await knowledgeStoreApi.listDocuments();
    setDocsLoading(false);
    if (result.ok && result.data) setDocs(result.data);
    else reportError.current?.(result.error || 'Failed to load knowledge store');
  }, []);

  useEffect(() => {
    if (picker) void refreshDocs();
  }, [picker, refreshDocs]);

  const ksOptions = useMemo(
    () => docs.map((d) => ({ value: d.title, label: d.title })),
    [docs]
  );

  const selectedFilenames = useMemo(
    () => value.attached.map((a) => a.filename),
    [value.attached]
  );

  const setSelected = (names: string[]) => {
    onChange({
      ...value,
      attached: names.map((filename) => ({ filename })),
    });
  };

  const removeInline = (filename: string) => {
    onChange({
      ...value,
      inline: value.inline.filter((f) => f.filename !== filename),
    });
  };

  const onDrop = useCallback((accepted: File[]) => {
    const oversize = accepted.filter((f) => f.size > MAX_INLINE_FILE_BYTES);
    if (oversize.length) {
      reportError.current?.(
        `These files are too large for inline upload (>2 MB): ${oversize
          .map((f) => f.name)
          .join(', ')}. Save them to the knowledge store instead.`
      );
    }
    const ok = accepted.filter((f) => f.size <= MAX_INLINE_FILE_BYTES);
    if (!ok.length) return;
    setPendingUploads(ok.map((file) => ({ file, size: file.size })));
    setSaveModalOpen(true);
  }, []);

  const dropzone = useDropzone({ onDrop, multiple: true });

  const closeModal = () => {
    setSaveModalOpen(false);
    setPendingUploads([]);
  };

  const attachInline = async () => {
    setUploading(true);
    try {
      const next: InlineTaskFile[] = [...value.inline];
      for (const { file } of pendingUploads) {
        const b64 = await fileToBase64(file);
        if (next.some((f) => f.filename === file.name)) continue;
        next.push({
          filename: file.name,
          mime: file.type || undefined,
          content_b64: b64,
        });
      }
      onChange({ ...value, inline: next });
    } finally {
      setUploading(false);
      closeModal();
    }
  };

  const saveToKsAndAttach = async () => {
    setUploading(true);
    setUploadError(null);
    const files = pendingUploads.map((p) => p.file);
    setUploadProgress({
      phase: 'uploading',
      loadedBytes: 0,
      totalBytes: files.reduce((sum, f) => sum + f.size, 0),
      bytesPerSecond: 0,
      etaSeconds: null,
    });
    try {
      const result = await knowledgeStoreApi.uploadDocumentsWithProgress(
        files,
        (snapshot) => setUploadProgress(snapshot)
      );
      if (!result.ok || !result.data) {
        setUploadError(result.error || 'Upload failed');
        reportError.current?.(result.error || 'Upload failed');
        return;
      }
      const newAttached = [...value.attached];
      for (const row of result.data) {
        if (row.error) {
          reportError.current?.(`${row.filename}: ${row.error}`);
          continue;
        }
        if (newAttached.some((a) => a.filename === row.filename)) continue;
        newAttached.push({ filename: row.filename });
      }
      onChange({ ...value, attached: newAttached });
      void refreshDocs();
      // Brief "Uploaded and indexed" beat before the modal closes.
      await new Promise((r) => window.setTimeout(r, 800));
    } finally {
      setUploading(false);
      setUploadProgress(null);
      closeModal();
    }
  };

  const attachedCount = value.attached.length + value.inline.length;

  if (compact && !picker) {
    return (
      <>
        <Button
          variant="subtle"
          size="xs"
          leftSection={<IconPaperclip size={14} />}
          onClick={() => setPicker(true)}
        >
          {attachedCount
            ? `Attached (${attachedCount})`
            : 'Attach files'}
        </Button>
        <SaveToKsModal
          open={saveModalOpen}
          files={pendingUploads}
          uploading={uploading}
          progress={uploadProgress}
          errorDetail={uploadError}
          onCancel={closeModal}
          onAttachOnly={attachInline}
          onSaveAndAttach={saveToKsAndAttach}
        />
      </>
    );
  }

  return (
    <Stack gap="xs">
      <Group justify="space-between" align="center">
        <Group gap={6}>
          <IconPaperclip size={16} className="text-[var(--textSoft)]" />
          <Text size="sm" fw={500}>
            Attachments {attachedCount ? `(${attachedCount})` : ''}
          </Text>
        </Group>
        {compact && (
          <Button
            variant="subtle"
            size="xs"
            onClick={() => setPicker(false)}
          >
            Close
          </Button>
        )}
      </Group>

      <Tabs defaultValue="knowledge-store" variant="pills">
        <Tabs.List>
          <Tabs.Tab
            value="knowledge-store"
            leftSection={<IconDatabase size={14} />}
          >
            From knowledge store
          </Tabs.Tab>
          <Tabs.Tab value="upload" leftSection={<IconCloudUpload size={14} />}>
            Upload new
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="knowledge-store" pt="xs">
          <MultiSelect
            placeholder={
              docsLoading
                ? 'Loading…'
                : ksOptions.length
                  ? 'Pick one or more files…'
                  : 'No files in the knowledge store yet'
            }
            data={ksOptions}
            value={selectedFilenames}
            onChange={setSelected}
            searchable
            clearable
            nothingFoundMessage="No matches"
            disabled={!docsLoading && !ksOptions.length}
          />
        </Tabs.Panel>

        <Tabs.Panel value="upload" pt="xs">
          <div
            {...dropzone.getRootProps()}
            className={`cursor-pointer rounded-xl border border-dashed border-white/15 p-4 text-center transition ${
              dropzone.isDragActive ? 'bg-white/10' : 'hover:bg-white/5'
            }`}
          >
            <input {...dropzone.getInputProps()} />
            <IconUpload className="mx-auto h-6 w-6 opacity-70" stroke={1.25} />
            <p className="mt-1 text-xs text-[var(--textSoft)]">
              {dropzone.isDragActive
                ? 'Drop the files here…'
                : 'Drag & drop or click to select (up to 2 MB each)'}
            </p>
          </div>
        </Tabs.Panel>
      </Tabs>

      {value.inline.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {value.inline.map((f) => (
            <Badge
              key={f.filename}
              variant="light"
              color="cyan"
              rightSection={
                <IconX
                  size={12}
                  style={{ cursor: 'pointer' }}
                  onClick={() => removeInline(f.filename)}
                />
              }
            >
              {f.filename} (one-shot)
            </Badge>
          ))}
        </div>
      )}

      <SaveToKsModal
        open={saveModalOpen}
        files={pendingUploads}
        uploading={uploading}
        progress={uploadProgress}
        errorDetail={uploadError}
        onCancel={closeModal}
        onAttachOnly={attachInline}
        onSaveAndAttach={saveToKsAndAttach}
      />
    </Stack>
  );
}

interface SaveToKsModalProps {
  open: boolean;
  files: PendingUpload[];
  uploading: boolean;
  progress: UploadProgressData | null;
  errorDetail: string | null;
  onCancel: () => void;
  onAttachOnly: () => void;
  onSaveAndAttach: () => void;
}

function SaveToKsModal({
  open,
  files,
  uploading,
  progress,
  errorDetail,
  onCancel,
  onAttachOnly,
  onSaveAndAttach,
}: SaveToKsModalProps) {
  return (
    <Modal
      opened={open}
      onClose={onCancel}
      title="Save to the knowledge store?"
      centered
      withCloseButton={!uploading}
      closeOnClickOutside={!uploading}
      closeOnEscape={!uploading}
    >
      <Stack gap="md">
        <Text size="sm">
          Save these files to the knowledge store so they're indexed and
          available to future tasks? Choose <strong>One-shot</strong> to send
          them only for this task without persisting anything.
        </Text>
        <ul className="list-disc pl-5 text-sm text-[var(--textSoft)]">
          {files.map((f) => (
            <li key={f.file.name}>
              {f.file.name}{' '}
              <span className="opacity-60">
                ({(f.size / 1024).toFixed(1)} KB)
              </span>
            </li>
          ))}
        </ul>
        {progress && <UploadProgress progress={progress} errorDetail={errorDetail} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel} disabled={uploading}>
            Cancel
          </Button>
          <Button
            variant="light"
            onClick={onAttachOnly}
            disabled={uploading}
          >
            One-shot (don't save)
          </Button>
          <Button
            onClick={onSaveAndAttach}
            disabled={uploading}
            loading={uploading}
            className="bg-blue-600 text-white hover:bg-blue-700"
          >
            Save to KS &amp; attach
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
