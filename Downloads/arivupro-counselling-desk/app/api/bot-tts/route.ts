export const dynamic = "force-dynamic";

// Streaming TTS endpoint — streams PCM audio chunks as they arrive from Gemini
// Client plays chunks progressively via Web Audio API (no waiting for full audio)
export async function POST(req: Request): Promise<Response> {
  try {
    const { text } = (await req.json()) as { text?: string };
    if (!text?.trim()) {
      return Response.json({ error: "No text." }, { status: 400 });
    }

    const key = process.env.GEMINI_API_KEY;
    if (!key) {
      return Response.json({ error: "TTS not configured." }, { status: 503 });
    }

    // Use streamGenerateContent for progressive audio delivery
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:streamGenerateContent?alt=sse&key=${key}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{ parts: [{ text: `<speak_style>Speak in a warm, friendly, colloquial Indian English style — like a knowledgeable friend from Chennai having a casual conversation. Natural rhythm, slightly informal tone, not robotic or formal.</speak_style>\n${text.slice(0, 560)}` }] }],
          generationConfig: {
            responseModalities: ["AUDIO"],
            speechConfig: {
              voiceConfig: {
                prebuiltVoiceConfig: { voiceName: "Kore" },
              },
            },
          },
        }),
        signal: AbortSignal.timeout(20000),
      }
    );

    if (!res.ok || !res.body) {
      // Fall back to non-streaming for error path
      return Response.json({ audio: null });
    }

    // Stream SSE from Gemini → extract audio chunks → stream raw base64 lines to client
    // Client will accumulate and decode each chunk independently
    const encoder = new TextEncoder();
    const geminiStream = res.body;

    const stream = new ReadableStream({
      async start(controller) {
        const reader = geminiStream.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";

            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              const jsonStr = line.slice(6).trim();
              if (!jsonStr || jsonStr === "[DONE]") continue;
              try {
                const chunk = JSON.parse(jsonStr);
                const audioData =
                  chunk?.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data;
                if (audioData) {
                  // Send each audio chunk as a newline-delimited base64 string
                  controller.enqueue(encoder.encode(audioData + "\n"));
                }
              } catch {
                // skip malformed JSON
              }
            }
          }
        } catch {
          // stream ended or aborted
        } finally {
          reader.releaseLock();
          controller.close();
        }
      },
    });

    return new Response(stream, {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Transfer-Encoding": "chunked",
        "Cache-Control": "no-cache",
        "Access-Control-Allow-Origin": "*",
      },
    });
  } catch {
    return Response.json({ audio: null });
  }
}
