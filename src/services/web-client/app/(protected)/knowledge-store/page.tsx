'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Card from '@/components/ui/card';
import Info from '@/components/ui/info';
import { FileUpload } from '@/components/ui/file-upload';
import { useDisclosure } from '@mantine/hooks';
import { Modal } from '@mantine/core';
import { config } from '@/utils/config';
import { IconTrash } from '@tabler/icons-react';

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

export default function KnowledgeStorePage() {
  const [toUpload, setToUpload] = useState<ToUpload[][]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [isMounted, setIsMounted] = useState(false);
  const [uploadOpened, { open: openUpload, close: closeUpload }] = useDisclosure(false);
  const [detailDoc, setDetailDoc] = useState<Document | null>(null);
  const [detailOpened, { open: openDetail, close: closeDetail }] = useDisclosure(false);

  const getDocuments = useCallback(async () => {
    const response = await fetch(ksUrl('/file'), { method: 'GET' });
    const data = await response.json();
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
    getDocuments();
  }, [toUpload, isMounted, getDocuments]);

  const getFileExtension = (fileName: string) => {
    const parts = fileName?.split('.');
    return parts?.length > 1 ? parts?.pop()!.toLowerCase() : 'unknown';
  };

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
    const formData = new FormData();
    toUpload.forEach((doc) => {
      formData.append('files', doc[0].file);
    });

    const response = await fetch(ksUrl('/file'), {
      method: 'POST',
      body: formData,
    });

    if (response.ok) {
      setToUpload([]);
      closeUpload();
    }
    await response.json();
    await getDocuments();
  };

  const deleteDocument = async (index: number) => {
    const response = await fetch(ksUrl(`/${documents[index].id}`), {
      method: 'DELETE',
    });
    if (response.ok) {
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
      <div className="flex-3 flex flex-col gap-5">
        <div className="gap-8 md:gap-10 ml-auto mr-auto grid grid-cols-2 md:flex md:grid-cols-4 md:gap-5 px-3 md:px-0 w-full md:w-200">
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
        <div className="overflow-x-auto px-0 md:px-0 w-full max-w-[75vw] md:max-w-full mx-auto">
          <Info
            title="Documents Stored"
            header={documentHeaders}
            body={documents.map((doc) => [
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
          />
        </div>
        <Modal
          opened={uploadOpened}
          onClose={closeUpload}
          title="Upload Files"
          size="auto"
          overlayProps={{ backgroundOpacity: 0.55, blur: 3 }}
          style={{ color: 'white' }}
          centered
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
            actions={modalActions}
            button="Upload"
            onButton={uploadDocuments}
          />
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
