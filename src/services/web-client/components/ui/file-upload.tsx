'use client';

import React, { useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { IconUpload } from "@tabler/icons-react";

interface FileUploadProps { onFilesSelected: (files: File[]) => void; }

export function FileUpload({ onFilesSelected }: FileUploadProps) {
  const onDrop = useCallback((acceptedFiles: File[]) => onFilesSelected(acceptedFiles), [onFilesSelected]);
  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, multiple: true });

  return (
    <div
      {...getRootProps()}
      className={`rounded-2xl border border-dashed border-white/15 p-8 text-center backdrop-blur-xl w-full mr-auto ml-auto transition mb-10 md:w-[700px]
        ${isDragActive ? "bg-white/10" : "bg-[var(--bgSoft)]/50 hover:bg-white/5"}`}
    >
      <input {...getInputProps()} />
      <IconUpload className="mx-auto h-12 w-12 opacity-70" stroke={1.25} />
      <p className="mt-2 text-sm text-[var(--textSoft)]">
        {isDragActive ? "Drop the files here…" : "Drag and drop files or click to select"}
      </p>
    </div>
  );
}