import React, { useEffect, useState } from 'react';
import Card from '../ui/card/card';
import Info from '../ui/info/info';
import { FileUpload } from '@/ui/files/file-upload';

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

const KnowledgeStore = () => {

    const baseUrl = process.env.NEXT_PUBLIC_KNOWLEDGE_STORE_URL || 'http://localhost:8080';

    const [toUpload, setToUpload] = useState<ToUpload[][]>([]);
    const [documents, setDocuments] = useState<Document[]>([]);
    const [isMounted, setIsMounted] = useState(false);

    useEffect(() => {
        const data = localStorage.getItem('knowledgeStoreDocuments');
        if (data) {
            setToUpload(JSON.parse(data));
        }
        setIsMounted(true);
        getDocuments();
    }, []);

    useEffect(() => {
        if (isMounted){
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

        const response = await fetch(`${baseUrl}/api/knowledge-store/file`, {
            method: 'POST',
            body: formData,
        });

        if (response.ok){
            setToUpload([]);
        }
        const data = await response.json();
        console.log('data up', data);
    };

    const getDocuments = async () => {
        const response = await fetch(`${baseUrl}/api/knowledge-store/file`, {
            method: 'GET',
        });
        const data = await response.json();
        if (response.ok){
            setDocuments(data['documents']);
        }
        console.log('data', data);
    };

    const deleteDocument = async (index: number) => {
        const response = await fetch(`${baseUrl}/api/knowledge-store/${documents[index].id}`, {
            method: 'DELETE',
        });
        if (response.ok){
            getDocuments();
        }
    };

    const uploadHeaders= [
        "Document",
        "Type",
        "Size",
        "Actions"
    ];
    const documentHeaders= [
        "Document",
        "Date",
        "Content",
        "Size (bytes)",
        "Actions"
    ];
    return (
        <div className="flex gap-3 mt-5">
            <div className="flex-3 flex flex-col gap-5">
                <div className="flex gap-5 space-between">
                    <Card
                        title="Total Documents"
                        number={documents.length}
                    />
                    <Card
                        title="Storage Used (bytes)"
                        number={documents.reduce((acc, doc) => acc + doc.size, 0)}
                    />
                </div>
                <FileUpload onFilesSelected={filesSelected}/>
                <Info
                    title="Files to Upload"
                    header={uploadHeaders}
                    body={toUpload.map((doc) => [
                        doc[0].file.name,
                        getFileExtension(doc[0].file.name),
                        `${doc[0].file.size} bytes`
                    ])}
                    actions={true}
                    button="Upload"
                    onButton={uploadDocuments}
                    onDelete={deleteLocalDocument}
                />
                <Info
                    title="Documents Stored"
                    header={documentHeaders}
                    body={documents.map((doc) => [
                        doc.title,
                        doc.date,
                        doc.content,
                        doc.size
                    ])}
                    actions={true}
                    onDelete={deleteDocument}
                />
            </div>
        </div>
    );
};

export default KnowledgeStore;