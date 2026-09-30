export type PdfBranding = {
  name: string;
  logo_url?: string | null;
  primary_color?: string | null;
};

const DEFAULT_COLOR = "#15603d";

export function resolvedPdfBranding(
  branding?: PdfBranding | null,
): { name: string; logo_url: string | null; primary_color: string } {
  return {
    name: branding?.name?.trim() || "ArivuPro Academy",
    logo_url: branding?.logo_url || null,
    primary_color: /^#[0-9A-Fa-f]{6}$/.test(branding?.primary_color || "")
      ? branding!.primary_color!
      : DEFAULT_COLOR,
  };
}
