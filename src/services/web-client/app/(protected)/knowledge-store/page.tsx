'use client';

import React, { useEffect, useState } from 'react';
import Card from '@/components/ui/card';
import Info from '@/components/ui/info';
import { FileUpload } from '@/components/ui/file-upload';
import { useDisclosure } from '@mantine/hooks';
import { Modal } from '@mantine/core';
import { config } from '@/utils/config';
import { MdDelete } from 'react-icons/md';
import { userApi } from '@/lib/users/api';

interface ToUpload {
  file: File;
  createdAt: string;
}

interface Document {
  id: number;
  title: string;
  content: string;
  date: string;
  size: number;
}

export default function KnowledgeStorePage() {

  const [toUpload, setToUpload] = useState<ToUpload[][]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [isMounted, setIsMounted] = useState(false);
  const [opened, { open, close }] = useDisclosure(false);

  useEffect(() => {
    const data = localStorage.getItem('knowledgeStoreDocuments');
    if (data) {
      setToUpload(JSON.parse(data));
    }
    setIsMounted(true);
    getDocuments();
  }, []);

  useEffect(() => {
    if (isMounted) {
      localStorage.setItem('knowledgeStoreDocuments', JSON.stringify(toUpload));
    }
    getDocuments();
  }, [toUpload, isMounted]);

  const getFileExtension = (fileName: string) => {
    const parts = fileName?.split('.');
    return parts?.length > 1 ? parts?.pop()!.toLowerCase() : 'unknown';
  };

  const deleteLocalDocument = (index: number) => {
    setToUpload(toUpload.filter((_, i) => i !== index));
  }

  const filesSelected = async (files: File[]) => {
    const newDocuments: ToUpload[][] = files.map((file) => [
      {
        file: file,
        createdAt: new Date().toLocaleDateString()
      }
    ]);

    setToUpload([...toUpload, ...newDocuments]);
  };

  const uploadDocuments = async () => {
    const formData = new FormData();
    toUpload.forEach((doc) => {
      formData.append('files', doc[0].file);
    });

    const response = await fetch(`${config.knowledgeStoreUrl}/api/knowledge-store/file`, {
      method: 'POST',
      body: formData,
    });

    if (response.ok) {
      setToUpload([]);
    }
    await response.json();
  };

  const getDocuments = async () => {
    const response = await fetch(`${config.knowledgeStoreUrl}/api/knowledge-store/file`, {
      method: 'GET',
    });
    const data = await response.json();
    if (response.ok) {
      setDocuments(data['documents']);
    }
  };

  const deleteDocument = async (index: number) => {
    const response = await fetch(`${config.knowledgeStoreUrl}/api/knowledge-store/${documents[index].id}`, {
      method: 'DELETE',
    });
    if (response.ok) {
      getDocuments();
    }
  };

  const uploadHeaders = [
    "Document",
    "Type",
    "Size",
    ""
  ];
  const documentHeaders = [
    "Document",
    "Date",
    "Content",
    "Size (bytes)",
    "Actions"
  ];

  const actions = [
    {
      icon: <MdDelete className="w-5 h-5" />,
      ariaLabel: "Delete file",
      onClick: deleteDocument,
    },
  ];

  const modalActions = [
    {
      icon: <MdDelete className="w-5 h-5" />,
      ariaLabel: "Delete file",
      onClick: deleteLocalDocument,
    },
  ];

  return (
    <div className="flex gap-3 mt-5">
      <div className="flex-3 flex flex-col gap-5">
        <div className="gap-8 md:gap-10 ml-auto mr-auto grid grid-cols-2 md:flex md:grid-cols-4 md:gap-5 px-3 md:px-0 w-full md:w-200">
          <Card
            title="Total Documents"
            number={documents.length}
          />
          <Card
            title="Storage Used (bytes)"
            number={documents.reduce((acc, doc) => acc + doc.size, 0)}
          />
        </div>
        {/* <FileUpload onFilesSelected={filesSelected}/> */}
        <div className="overflow-x-auto px-0 md:px-0 w-full max-w-[75vw] md:max-w-full mx-auto">
          <Info
            title="Documents Stored"
            header={documentHeaders}
            body={documents.map((doc) => [
              doc.title,
              doc.date,
              doc.content,
              doc.size
            ])}
            actions={actions}
            button="Add files"
            onButton={open}
          />
        </div>
        <Modal opened={opened} onClose={close} title="Upload Files" size="auto" overlayProps={{ backgroundOpacity: 0.55, blur: 3 }} style={{ color: 'white' }} centered>
          <FileUpload onFilesSelected={filesSelected} />
          <Info
            title="Files to Upload"
            header={uploadHeaders}
            body={toUpload.map((doc) => [
              doc[0].file.name,
              getFileExtension(doc[0].file.name),
              `${doc[0].file.size} bytes`
            ])}
            actions={modalActions}
            button="Upload"
            onButton={uploadDocuments}
          />
        </Modal>
      </div>
    </div>
  );
};
