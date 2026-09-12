# Large-document real-AI evidence — 12 Sep 2026

## Provider diagnosis

- The configured Gemini key returned the model from `models.list`, including
  `generateContent` support and a 65,536 output-token limit, but repeated direct
  calls to `gemini-2.5-flash:generateContent` returned HTTP 404. A direct call to
  `gemini-3.5-flash-lite` succeeded. Later, the same 2.5 call succeeded, proving
  the observed failure is intermittent rather than a malformed application
  payload.
- The fix uses `gemini-3.5-flash` as the current default and retries a
  model-specific 404 against `GEMINI_FALLBACK_MODEL` before using DeepSeek. A
  missing model is cached per worker so each later call does not repeat the same
  failed request.
- DeepSeek's official Chat Completions documentation states that `max_tokens`
  accepts 1–393,216 and defaults to 8K in non-thinking mode. The application's
  former 8,192 setting was therefore its own ceiling, not the provider maximum.
  The large-JSON fallback now requests 65,536.

Provider references:

- <https://api-docs.deepseek.com/api/create-chat-completion>
- <https://ai.google.dev/gemini-api/docs/models>

## Real run

Command (real provider calls, no mocks):

```text
APP_ENV=development venv/bin/python -m scripts.review_large_document_e2e ../docs/python-basics-sample-chapters.pdf
```

Result: passed in 83.86 seconds.

- Source: `docs/python-basics-sample-chapters.pdf`, 98 pages, 107,010 extracted
  characters.
- Routing: exceeded the 100,000-character threshold and produced three chunks
  spanning approximately pages 2–33, 34–68, and 69–98.
- Topic consolidation: 16 raw topics became 14 consolidated topics.
- Late source: topic **Working with Strings and Numbers**, approximate pages
  69–98. The matched source fact was on page 92:

  > You cannot convert a string that looks like a floating-point number (e.g.,
  > "12.0") directly into an integer using int() because it would result in a
  > loss of precision, raising a ValueError.

- Selected-topic generation material: 1,474 characters; the page-92 fact was
  present and no document-wide truncation was applied.
- Generated question:

  > What is the result of attempting to run the code int("12.0") in Python?

  The generated answer was option `c`; its explanation explicitly states that
  conversion raises `ValueError` because of precision loss.
- Exact mix requested and received: one `mcq_single`, one `true_false`, and one
  `fill_blank`.
- Production-shaped logical calls: six — one profile, three parallel MAP, one
  REDUCE, and one final generation. All six succeeded through Gemini.
- Test-only DeepSeek verification: the same real REDUCE input returned valid
  JSON with 14 topics at `max_tokens=65536`; it did not finish with truncation.
  This extra provider call is not part of the production call path.
- Total external calls during this evidence run: seven (the six production-
  shaped calls plus the forced DeepSeek verification).

## Honest caveat

The non-blocking verbatim spot-check examined five consolidated facts. One
matched a meaningful source substring and four emitted warnings. This does not
invalidate the demonstrated page-92 fact/question pairing, but it shows the
model still paraphrases some consolidated facts despite the prompt. The current
product requirement is to log this visibility signal rather than block the job.
