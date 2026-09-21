# Decision: Use Gemini directly for document → quiz, not a separate OCR

> **Historical decision, narrowed by the current implementation.** There is
> still no separate OCR service/library. Typed PDFs and DOCX are extracted
> locally and use the DeepSeek-first text router; only scanned PDFs/images in
> the existing-quiz Extract flow use Gemini vision. Generate Quiz rejects scans
> without a usable text layer. See `docs/current-ai-document-workflow.md`.

**Status:** Recommended
**Date:** 5 August 2026
**Applies to:** Quiz Generator v1 — the "Import questions from a document" feature
**Prepared for:** Technical Lead / Project stakeholders

---

## 1. Summary (TL;DR)

For extracting MCQs from uploaded question-bank / past-paper documents, we
recommend reading the document **directly with Gemini** (which we already use
and pay for) instead of adding a **separate OCR service** (e.g. Mistral OCR).

A dedicated OCR adds a second vendor, a second API key, an extra processing
step, and slightly **more** cost — while providing **no capability we don't
already have**, because our documents are printed/digital (no handwriting) and
Gemini is already a multimodal model that reads PDFs and images natively.

**Decision: skip the dedicated OCR; use Gemini-direct.** Revisit only if a real
document proves Gemini insufficient (criteria in §6).

---

## 2. Context — what we are actually building

Users upload a **printed/digital question bank or past paper** (PDF or image)
containing multiple-choice questions: question text, four options, the marked
correct answer, and sometimes tables, formulas, and diagrams. The system must
extract these into structured MCQs and present them as a practice quiz.

Key fact: **there is no handwriting** in these documents, and they are already
digital or cleanly printed.

---

## 3. What OCR is, and when it is actually needed

OCR (Optical Character Recognition) converts **images of text into
machine-readable text**. Its genuine, hard-to-replace value is for:

- **Handwriting** recognition,
- **Scanned paper / photographs** where text is baked into pixels,
- **Very high-volume** pipelines wanting cheap, deterministic text.

None of these describe our case. Our documents are printed and digital, in
modest volumes. OCR's signature strengths **do not apply to us**.

---

## 4. The core point: Gemini is already a multimodal reader

Gemini 2.5 is **multimodal** — a PDF or image can be sent to it **directly**,
and it reads the text, tables, and math **and** structures the result into MCQ
JSON **in a single call**. A separate OCR step therefore duplicates work Gemini
already performs. We would be paying a second vendor to pre-process something
Gemini consumes natively.

---

## 5. Comparison for our use case

| Dimension | **Gemini-direct** (recommended) | **Dedicated OCR + LLM** |
|---|---|---|
| Steps | 1 (document → Gemini → MCQs) | 2 (document → OCR text → LLM → MCQs) |
| Vendors / API keys | **1** (Gemini, already integrated) | **2** (OCR vendor **+** Gemini/other) |
| Cost per document | **~₹2–3** (Flash); under ₹0.50 (Flash-Lite) | **~₹3+** (OCR ~₹1.7 + structuring ~₹1) |
| Text / tables / math | Handled well | Handled well (roughly equal) |
| Handwriting | Not needed for us | Not needed for us |
| Latency | One round-trip | Two round-trips (slower) |
| Failure points | Fewer | More (two systems can compound errors) |
| New capability gained | — | **None for our documents** |

**Conclusion:** the OCR route is the **same cost or more**, with **more
complexity and more moving parts**, for **no additional capability**.

---

## 6. The one nuance — displaying diagrams — and why it still doesn't need OCR

Some questions include diagrams that must be **shown** to the student. A
dedicated OCR conveniently returns cropped figure images. However, this does
**not** require a paid OCR vendor, because:

- We already have **`pypdfium2`** (installed with `pdfplumber`), which
  **renders PDF pages to images**.
- Gemini can return a diagram's **coordinates**; we crop it from the page
  render ourselves — or simply display the page region alongside the question.

So even the image requirement is solvable with tools **already in the project**.

---

## 7. When a dedicated OCR *would* be justified (revisit criteria)

We would reconsider **only** if, during real testing, we hit one of these:

1. **Very large documents at high volume** (hundreds of pages, thousands of
   docs) where converting to text first is measurably cheaper/faster.
2. **Extremely formula-heavy** material where Gemini's math transcription is
   proven unreliable — in which case a *math specialist* (e.g. Mathpix), **not**
   a generic OCR, would be evaluated.
3. Gemini's extraction accuracy on our actual documents proves insufficient in
   testing.

None of these is currently true for a CA-Foundation question-bank import.

---

## 8. Decision & rationale

**Decision:** Build the "Import questions" feature on **Gemini-direct**. Do not
add a separate OCR vendor at this stage.

**Rationale:**
- **No cost benefit** — OCR is the same or slightly more expensive (§9).
- **No capability benefit** — no handwriting; Gemini reads documents natively.
- **Lower complexity & risk** — one vendor, one key, one call, fewer failure
  points.
- **Reversible** — the structuring and storage logic are independent of the
  reader, so switching to OCR later (if a revisit criterion is met) is a small,
  isolated change.

This is a data-driven, low-risk, and easily reversible choice.

---

## 9. Appendix — cost basis

Official Gemini pricing (per 1M tokens), converted at ~₹86/USD (rate fluctuates):

| Model | Input (text/image/PDF) | Output |
|---|---|---|
| Flash-Lite | ~₹9 | ~₹34 |
| Flash | ~₹26 | ~₹215 |
| Pro | ~₹108 (≤200k) | ~₹860 |

Estimate for one upload (~20 pages ≈ ~12k input tokens; ~40 MCQs ≈ ~8k output):
- **Gemini Flash:** ≈ **₹2–3 per document**; ~₹2,150 for 1,000 documents/month.
- **Gemini Flash-Lite:** ≈ **under ₹0.50 per document**; ~₹350 for 1,000/month.
- A **free tier** covers low volume.

Dedicated OCR path: OCR ≈ ₹1.7 for a 20-page doc **plus** LLM structuring ≈ ₹1,
i.e. **≈ ₹3+ per document, across two vendors** — no cheaper than Gemini-direct.

*Figures are order-of-magnitude estimates; token counts and exchange rates vary.
The conclusion (cents/rupees per document; OCR not cheaper) is robust to normal
variation.*
