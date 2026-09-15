"use client";

import { useEffect, useRef, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  DOCUMENT_UPLOAD_MAX_MB,
  DocumentOut,
  UploadResult,
  listDocuments,
  uploadDocument,
} from "@/lib/api";

export function DocumentUpload() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [documents, setDocuments] = useState<DocumentOut[]>([]);

  // Load the existing document list once when the page mounts.
  useEffect(() => {
    listDocuments()
      .then(setDocuments)
      .catch((e) => setError(e.message));
  }, []);

  async function handleFileChange(
    event: React.ChangeEvent<HTMLInputElement>,
  ) {
    const file = event.target.files?.[0];
    if (!file) return;

    setError(null);
    setResult(null);
    setUploading(true);
    try {
      const uploaded = await uploadDocument(file);
      setResult(uploaded);
      // Refresh the list so the new document appears.
      setDocuments(await listDocuments());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
      // Reset the input so the same file can be re-selected if needed.
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Upload teaching material</CardTitle>
          <CardDescription>
            PDF or DOCX, up to {DOCUMENT_UPLOAD_MAX_MB} MB. We&apos;ll extract the text so you can
            generate quizzes from it.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.docx"
            onChange={handleFileChange}
            disabled={uploading}
            className="block text-sm file:mr-4 file:rounded-md file:border-0 file:bg-primary file:px-4 file:py-2 file:text-sm file:font-medium file:text-primary-foreground hover:file:bg-primary/90"
          />
          {uploading && (
            <p className="text-sm text-muted-foreground">
              Uploading and extracting text…
            </p>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle>{result.document.original_filename}</CardTitle>
            <CardDescription>
              Extracted {result.char_count.toLocaleString()} characters
              {result.truncated && " (showing the first 5,000)"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/40 p-4 text-sm">
              {result.text_preview || "(No text found — is this a scanned PDF?)"}
            </pre>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Your documents</CardTitle>
          <CardDescription>Everything uploaded in your institution.</CardDescription>
        </CardHeader>
        <CardContent>
          {documents.length === 0 ? (
            <p className="text-sm text-muted-foreground">No documents yet.</p>
          ) : (
            <ul className="flex flex-col divide-y">
              {documents.map((doc) => (
                <li
                  key={doc.id}
                  className="flex items-center justify-between gap-4 py-3 text-sm"
                >
                  <span className="truncate">{doc.original_filename}</span>
                  <span className="flex items-center gap-3 text-muted-foreground">
                    <span className="uppercase">{doc.file_type}</span>
                    <StatusBadge status={doc.status} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "completed"
      ? "bg-green-100 text-green-800"
      : status === "failed"
        ? "bg-red-100 text-red-800"
        : "bg-muted text-foreground";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {status}
    </span>
  );
}
