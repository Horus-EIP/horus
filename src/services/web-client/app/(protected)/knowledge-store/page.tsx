'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Card from '@/components/ui/card';
import Info from '@/components/ui/info';
import { FileUpload } from '@/components/ui/file-upload';
import { useDebouncedValue, useDisclosure } from '@mantine/hooks';
import { Modal } from '@mantine/core';
import { config } from '@/utils/config';
import { IconTrash } from '@tabler/icons-react';
import { UploadProgress } from '@/components/knowledge-store/upload-progress';
import { AlreadyStoredWarning } from '@/components/knowledge-store/already-stored-warning';
import { namesAlreadyStored } from '@/lib/knowledge-store/stored-names';
import { requestedDocumentId } from '@/lib/chat/answer-sources';
import {
  knowledgeStoreApi,
  type KnowledgeStoreCategory,
  type SmartSearchHit,
  type UploadProgress as UploadProgressData,
} from '@/lib/knowledge-store/api';

const ALL_CATEGORIES = '';
const SEARCH_RESULT_LIMIT = 10;
const SEARCH_DEBOUNCE_MS = 300;

interface ToUpload {
  file: File;
  createdAt: string;
}

/** Matches GET /file list payload (full file body is not returned). */
interface Document {
  id: string;
  title: string;
  date: string;
  size: number;
  summary: string;
  excerpt: string;
  category: string;
  document_type: string;
  confidence_score?: number;
}

function ksUrl(path: string): string {
  const base = config.knowledgeStoreUrl.replace(/\/$/, '');
  const prefix = config.knowledgeStoreApiPrefix;
  return `${base}${prefix}${path}`;
}

function isSearchHitFor(hit: SmartSearchHit, doc: Document): boolean {
  if (hit.id) return hit.id === doc.id;
  return hit.metadata.title === doc.title && hit.metadata.date === doc.date;
}

export default function KnowledgeStorePage() {
  const [toUpload, setToUpload] = useState<ToUpload[][]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [isMounted, setIsMounted] = useState(false);
  const [uploadOpened, { open: openUpload, close: closeUpload }] = useDisclosure(false);
  const [detailDoc, setDetailDoc] = useState<Document | null>(null);
  const [detailOpened, { open: openDetail, close: closeDetail }] = useDisclosure(false);
  const [uploadProgress, setUploadProgress] =
    useState<UploadProgressData | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearchTerm] = useDebouncedValue(searchTerm.trim(), SEARCH_DEBOUNCE_MS);
  const [searchHits, setSearchHits] = useState<SmartSearchHit[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [categories, setCategories] = useState<KnowledgeStoreCategory[]>([]);
  const [categoryFilter, setCategoryFilter] = useState(ALL_CATEGORIES);
  const isUploading =
    uploadProgress?.phase === 'uploading' ||
    uploadProgress?.phase === 'processing';

  const latestDocumentsRequest = React.useRef(0);
  const requestedDocumentShown = React.useRef(false);

  const getDocuments = useCallback(async () => {
    const request = ++latestDocumentsRequest.current;
    const response = await fetch(ksUrl('/file'), { method: 'GET' });
    const data = await response.json();
    if (request !== latestDocumentsRequest.current) return;
    if (response.ok && Array.isArray(data.documents)) {
      setDocuments(
        data.documents.map((d: Record<string, unknown>) => ({
          id: String(d.id ?? ''),
          title: String(d.title ?? 'Untitled'),
          date: String(d.date ?? ''),
          size: typeof d.size === 'number' ? d.size : Number(d.size) || 0,
          summary: String(d.summary ?? d.excerpt ?? ''),
          excerpt: String(d.excerpt ?? ''),
          category: String(d.category ?? 'general'),
          document_type: String(d.document_type ?? 'unknown'),
          confidence_score:
            typeof d.confidence_score === 'number' ? d.confidence_score : undefined,
        })),
      );
    }
  }, []);

  useEffect(() => {
    const data = localStorage.getItem('knowledgeStoreDocuments');
    if (data) {
      setToUpload(JSON.parse(data));
    }
    setIsMounted(true);
    getDocuments();
  }, [getDocuments]);

  useEffect(() => {
    if (isMounted) {
      localStorage.setItem('knowledgeStoreDocuments', JSON.stringify(toUpload));
    }
  }, [toUpload, isMounted]);

  useEffect(() => {
    if (requestedDocumentShown.current) return;
    const wanted = requestedDocumentId(window.location.search);
    const doc = wanted ? documents.find((candidate) => candidate.id === wanted) : undefined;
    if (!doc) return;
    requestedDocumentShown.current = true;
    setDetailDoc(doc);
    openDetail();
  }, [documents, openDetail]);

  const getFileExtension = (fileName: string) => {
    const parts = fileName?.split('.');
    return parts?.length > 1 ? parts?.pop()!.toLowerCase() : 'unknown';
  };

  const getCategories = useCallback(async () => {
    const result = await knowledgeStoreApi.getCategories();
    if (!result.ok) return;
    const loaded = result.data ?? [];
    setCategories(loaded);
    setCategoryFilter((current) =>
      loaded.some((entry) => entry.category === current) ? current : ALL_CATEGORIES,
    );
  }, []);

  useEffect(() => {
    getCategories();
  }, [documents, getCategories]);

  useEffect(() => {
    if (!debouncedSearchTerm) {
      setSearchHits([]);
      setSearchError(null);
      return;
    }
    let cancelled = false;
    knowledgeStoreApi
      .smartSearch({
        query: debouncedSearchTerm,
        n_results: SEARCH_RESULT_LIMIT,
        categories: categoryFilter === ALL_CATEGORIES ? undefined : [categoryFilter],
      })
      .then((result) => {
        if (cancelled) return;
        setSearchHits(result.ok ? (result.data ?? []) : []);
        setSearchError(result.ok ? null : `Search failed: ${result.error}`);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedSearchTerm, categoryFilter, documents]);

  const visibleDocuments = useMemo(() => {
    const candidates = debouncedSearchTerm
      ? searchHits
          .map((hit) => documents.find((doc) => isSearchHitFor(hit, doc)))
          .filter((doc): doc is Document => doc !== undefined)
      : documents;
    if (categoryFilter === ALL_CATEGORIES) return candidates;
    return candidates.filter((doc) => doc.category === categoryFilter);
  }, [debouncedSearchTerm, searchHits, documents, categoryFilter]);

  const categoryOptions = [
    { value: ALL_CATEGORIES, label: 'All categories' },
    ...categories.map((entry) => ({
      value: entry.category,
      label: `${entry.category} (${entry.count})`,
    })),
  ];

  const alreadyStoredNames = useMemo(
    () =>
      namesAlreadyStored(
        toUpload.map((doc) => doc[0]?.file?.name ?? ''),
        documents.map((doc) => doc.title),
      ),
    [toUpload, documents],
  );

  const deleteLocalDocument = (index: number) => {
    setToUpload(toUpload.filter((_, i) => i !== index));
  };

  const filesSelected = async (files: File[]) => {
    const newDocuments: ToUpload[][] = files.map((file) => [
      { file, createdAt: new Date().toLocaleDateString() },
    ]);
    setToUpload([...toUpload, ...newDocuments]);
  };

  const uploadDocuments = async () => {
    const files = toUpload.map((doc) => doc[0].file);
    if (!files.length) return;

    setUploadError(null);
    setUploadProgress({
      phase: 'uploading',
      loadedBytes: 0,
      totalBytes: files.reduce((sum, f) => sum + f.size, 0),
      bytesPerSecond: 0,
      etaSeconds: null,
    });

    const result = await knowledgeStoreApi.uploadDocumentsWithProgress(
      files,
      (snapshot) => setUploadProgress(snapshot)
    );

    if (result.ok) {
      setToUpload([]);
      await getDocuments();
      // Hold the "Uploaded and indexed" confirmation on screen for a beat so
      // the user actually sees the success state before the modal closes.
      window.setTimeout(() => {
        setUploadProgress(null);
        closeUpload();
      }, 1200);
    } else {
      setUploadError(result.error || 'Upload failed');
    }
  };

  const deleteDocument = async (index: number) => {
    const response = await fetch(ksUrl(`/${visibleDocuments[index].id}`), {
      method: 'DELETE',
    });
    if (response.ok || response.status === 404) {
      getDocuments();
    }
  };

  const openDocumentDetail = (doc: Document) => {
    setDetailDoc(doc);
    openDetail();
  };

  const uploadHeaders = ['Document', 'Type', 'Size', ''];
  const documentHeaders = ['Document', 'Category', 'Summary', 'Date', 'Size', 'Details'];

  const actions = [
    {
      icon: <IconTrash className="w-5 h-5" stroke={1.25} />,
      ariaLabel: 'Delete file',
      onClick: deleteDocument,
    },
  ];

  const modalActions = [
    {
      icon: <IconTrash className="w-5 h-5" stroke={1.25} />,
      ariaLabel: 'Remove from queue',
      onClick: deleteLocalDocument,
    },
  ];

  return (
    <div className="flex gap-3 mt-5">
      <div className="flex-3 flex flex-col gap-5 min-w-0">
        <div className="gap-8 md:gap-10 ml-auto mr-auto grid grid-cols-2 md:flex md:grid-cols-4 md:gap-5 px-3 md:px-0 w-full md:max-w-200">
          <Card title="Total Documents" number={documents.length} />
          <Card
            title="Storage Used (bytes)"
            number={documents.reduce((acc, doc) => acc + doc.size, 0)}
          />
        </div>
        <p className="mx-auto max-w-3xl px-3 text-center text-sm text-[var(--textSoft)]">
          Upload runs automatic analysis in the knowledge store (category, entities, summary).
          The table shows that summary and a short excerpt, not the full file.
        </p>
        <div className="overflow-x-auto px-0 md:px-0 w-full mx-auto">
          <Info
            title="Documents Stored"
            header={documentHeaders}
            body={visibleDocuments.map((doc) => [
              doc.title,
              doc.category,
              doc.summary.length > 180 ? `${doc.summary.slice(0, 180)}...` : doc.summary,
              doc.date,
              doc.size,
              <button
                key={`d-${doc.id}`}
                type="button"
                className="rounded-lg border border-white/15 bg-white/5 px-2 py-1 text-xs text-sky-200 hover:bg-white/10"
                onClick={() => openDocumentDetail(doc)}
              >
                View
              </button>,
            ])}
            actions={actions}
            button="Add files"
            onButton={openUpload}
            searchConfig={{
              placeholder: 'Search documents...',
              value: searchTerm,
              onChange: setSearchTerm,
            }}
            selectConfig={{
              value: categoryFilter,
              onChange: setCategoryFilter,
              options: categoryOptions,
            }}
          />
          {searchError && (
            <p className="mt-2 px-3 text-sm text-rose-300">{searchError}</p>
          )}
        </div>
        <Modal
          opened={uploadOpened}
          onClose={() => {
            if (isUploading) return; // don't let the user yank an in-flight upload
            setUploadProgress(null);
            closeUpload();
          }}
          title="Upload Files"
          size="auto"
          overlayProps={{ backgroundOpacity: 0.55, blur: 3 }}
          style={{ color: 'white' }}
          centered
          withCloseButton={!isUploading}
          closeOnClickOutside={!isUploading}
          closeOnEscape={!isUploading}
        >
          <FileUpload onFilesSelected={filesSelected} />
          <Info
            title="Files to Upload"
            header={uploadHeaders}
            body={toUpload.map((doc) => [
              doc[0].file.name,
              getFileExtension(doc[0].file.name),
              `${doc[0].file.size} bytes`,
            ])}
            actions={isUploading ? [] : modalActions}
            button={isUploading ? undefined : 'Upload'}
            onButton={isUploading ? undefined : uploadDocuments}
          />
          <AlreadyStoredWarning names={alreadyStoredNames} className="mt-3">
            Uploading adds another copy with the same name.
          </AlreadyStoredWarning>
          {uploadProgress && (
            <div className="mt-3">
              <UploadProgress
                progress={uploadProgress}
                errorDetail={uploadError}
              />
            </div>
          )}
        </Modal>

        <Modal
          opened={detailOpened}
          onClose={() => {
            closeDetail();
            setDetailDoc(null);
          }}
          title={detailDoc?.title ?? 'Document'}
          size="lg"
          overlayProps={{ backgroundOpacity: 0.55, blur: 3 }}
          style={{ color: 'white' }}
          centered
        >
          {detailDoc && (
            <div className="flex flex-col gap-3 text-sm text-[var(--text)]">
              <p>
                <span className="text-[var(--textSoft)]">Category:</span> {detailDoc.category}{' '}
                <span className="text-[var(--textSoft)]">· Type:</span> {detailDoc.document_type}
              </p>
              <p>
                <span className="text-[var(--textSoft)]">Indexed:</span> {detailDoc.date}{' '}
                <span className="text-[var(--textSoft)]">· Size (bytes):</span> {detailDoc.size}
                {detailDoc.confidence_score != null && (
                  <>
                    {' '}
                    <span className="text-[var(--textSoft)]">· Analysis confidence:</span>{' '}
                    {detailDoc.confidence_score.toFixed(2)}
                  </>
                )}
              </p>
              <div>
                <p className="mb-1 font-medium text-[var(--textSoft)]">Summary (from store analysis)</p>
                <p className="whitespace-pre-wrap rounded-lg border border-white/10 bg-black/20 p-3">
                  {detailDoc.summary}
                </p>
              </div>
              {detailDoc.excerpt && detailDoc.excerpt !== detailDoc.summary && (
                <div>
                  <p className="mb-1 font-medium text-[var(--textSoft)]">Text excerpt</p>
                  <p className="whitespace-pre-wrap rounded-lg border border-white/10 bg-black/20 p-3 text-[var(--textSoft)]">
                    {detailDoc.excerpt}
                  </p>
                </div>
              )}
            </div>
          )}
        </Modal>
      </div>
    </div>
  );
}
