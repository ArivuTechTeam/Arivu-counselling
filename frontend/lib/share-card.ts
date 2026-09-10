/**
 * Render a DOM node to a high-res PNG and trigger a download.
 * Fails quietly — if capture ever hiccups (rare font/CORS case), the on-screen
 * card and the WhatsApp text share still work, so the user is never blocked.
 */
export async function downloadCardImage(
  node: HTMLElement,
  filename: string,
): Promise<void> {
  try {
    const { toPng } = await import("html-to-image");
    const dataUrl = await toPng(node, {
      pixelRatio: 2, // crisp on retina / when zoomed
      cacheBust: true,
      backgroundColor: "#0f1f17",
    });
    const link = document.createElement("a");
    link.href = dataUrl;
    link.download = filename;
    link.click();
  } catch {
    /* non-critical — sharing still works via WhatsApp */
  }
}
