import { pdf, type DocumentProps } from "@react-pdf/renderer";
import type { ReactElement } from "react";

/** Render a @react-pdf document to a Blob and trigger a browser download. */
export async function downloadPdf(
  doc: ReactElement<DocumentProps>,
  filename: string,
) {
  const blob = await pdf(doc).toBlob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".pdf") ? filename : `${filename}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Filesystem-safe slug for filenames. */
export function slug(s: string): string {
  return (s || "document")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 60);
}
