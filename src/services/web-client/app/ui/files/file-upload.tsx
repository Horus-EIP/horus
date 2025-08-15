import React, { useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { Upload } from "lucide-react"

interface FileUploadProps {
    onFilesSelected: (files: File[]) => void;
}

export function FileUpload({ onFilesSelected }: FileUploadProps) {
    const onDrop = useCallback((acceptedFiles: File[]) => {
        onFilesSelected(acceptedFiles);
    }, [onFilesSelected]);

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        multiple: true
    });

    return (
        <div
            {...getRootProps()}
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors
                ${isDragActive ? "border-blue-500 bg-[var(--bgSoft)]" : "border-gray-300 hover:border-gray-400"}
            `}
        >
            <input {...getInputProps()} />
            <Upload className="mx-auto h-12 w-12 text-gray-400"/>
            <p className="mt-2text-sm text-gray-600">
                {isDragActive ? "Drop the files here..." : "Drag 'n' drop some files here or click to select files"}
            </p>
        </div>
    );
}