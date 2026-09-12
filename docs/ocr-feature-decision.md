# OCR for scanned documents — research & decision brief

**Feature branch:** `ocr-pavyaa`
**Status:** Research complete · key decisions made · **not yet built** (OCR engine choice still open)
**Date:** 10-Sep-2026
**Audience:** the author (to learn the trade-offs) and teammates (to pick up full context)

---

## 1. The goal (plain English)

Teachers already upload documents to create quizzes. Some of those uploads are
**scans/photos of question papers** (a printed exam paper photographed, or a
scanned PDF) rather than a clean digital file. The system must:

1. Detect whether an upload is a **typed/digital** document or a **scanned image**.
2. For scanned documents, **read the text out of the image (OCR)**, then use an
   AI model to figure out **which part is a question and which is the answer**,
   and turn it into a proper quiz that flows into the normal **review → publish**
   pipeline.

The proposed twist: instead of paying an AI vision model to read the scan, use a
**free OCR** step to get the text, then send that text to **DeepSeek** (we already
have a DeepSeek API key) to structure it into questions/answers.

---

## 2. How extraction works TODAY (the baseline we're changing)

The platform already has "smart routing" for the **Extract quiz** feature
(`backend/app/services/quiz_extraction.py`):

```
Upload
  ├─ Typed PDF / DOCX (has a real text layer)
  │     → pull text for free (pdfplumber / python-docx)
  │     → Gemini text (with DeepSeek fallback) structures the questions
  │
  └─ Scanned PDF / image (little/no text layer)
        → Gemini VISION reads the image AND structures the questions (one call)
```

Key point: **for scans, we currently use Gemini vision**, which:
- reads printed **and handwritten** text very well,
- understands layout + answer keys, and
- does OCR **and** question-structuring in a **single** call.

So this feature is really about **replacing the Gemini-vision leg for scans**
with a cheaper `free OCR → DeepSeek` path.

---

## 3. The proposed pipeline

```
Teacher uploads a document
        │
        ▼
Is it typed (has text layer) or scanned (image)?
        │
        ├── typed  ──► existing text path (unchanged)
        │
        └── scanned ─► OCR extracts raw text
                         │
                         ▼
                   DeepSeek analyses the raw text:
                   "which is a question, which is the answer"
                         │
                         ▼
                   Draft quiz → Review queue → Publish
```

This is a **two-step** pipeline (OCR, then DeepSeek), versus the current
**one-step** Gemini vision.

---

## 4. OCR options compared (research, Sep 2026)

| OCR option | Printed scans | Handwriting | Footprint / fit for our host (Railway) | Cost | Data privacy |
|---|---|---|---|---|---|
| **Tesseract** (self-hosted lib) | ~92% ✓ | **~45% ✗ (poor)** | ~10 MB, fast (~0.5s/page); 1-line Docker add | Free | Private (runs in our own container) |
| **EasyOCR** (self-hosted lib) | good | ~62% | ~500 MB + PyTorch, ~3× slower — **heavy** | Free | Private |
| **PaddleOCR** (self-hosted lib) | high | **~73% (best free)** + table/layout parsing | PyTorch/Paddle, GBs, slowest — **heavy, OOM risk** | Free | Private |
| **OCR.space API** (hosted) | good | weak–moderate | Zero infra (just HTTP); 25,000 req/month free | Free tier | **Documents leave** to a third party |
| **Google Cloud Vision API** (hosted) | excellent | excellent | Zero infra | 1,000/month free, then ~$1.50 / 1,000 | Documents leave |
| **Gemini vision** *(what we use now)* | excellent | **excellent** | Already built; OCR **+** question-structuring in one call | ~pennies per paper | Same as today (already on Gemini) |

**"Python library" vs "free market OCR" (the two things we wanted compared):**
- **Python libraries** (Tesseract / EasyOCR / PaddleOCR): run **inside our own
  backend**, no per-call fee, no data leaves our server. Cost = engineering +
  server resources. Tesseract is light; EasyOCR/PaddleOCR are heavy.
- **Free hosted OCR APIs** (OCR.space, Google Vision free tier): **no infra**,
  just an HTTP call, but the document is **sent to a third party** and free tiers
  have volume/file-size limits.

---

## 5. The engineering realities that actually drive the decision

1. **Handwriting is the trap.**
   The free OCR that is *light enough for our host* (Tesseract) is **bad at
   handwriting (~45%)** → it produces garbage → DeepSeek then has nothing real to
   structure. The engines that do handwriting well (PaddleOCR ~73%) are **heavy**
   (PyTorch, GBs) and risky on Railway. Meanwhile **Gemini vision (already
   integrated) is excellent at handwriting.**

2. **The cost saving is smaller than it sounds.**
   Gemini 2.5 Flash vision costs roughly **pennies per scanned paper**
   (≈258 tokens/page). So "free OCR" mainly buys **independence from Gemini** and
   **privacy**, not big money savings.

3. **Deployment is fine for the light option.**
   Backend deploys via a `Dockerfile` on `python:3.12-slim` (Debian). Adding
   Tesseract is a one-line change:
   `apt-get install -y tesseract-ocr poppler-utils` (poppler lets us turn scanned
   PDF pages into images via `pdf2image`). Heavy engines (Torch/Paddle) are the
   risky ones (slow builds, memory).

4. **Two-step vs one-step reliability.**
   `OCR → DeepSeek` has two failure points (bad OCR, then bad parse). Gemini
   vision is one step and reads layout/answer-keys directly. For **printed** scans
   the two-step path is fine and cheap; for handwriting it degrades.

---

## 6. Decisions made in the discussion

| Question | Decision | Why |
|---|---|---|
| What will teachers mostly scan? | **Printed / typed papers** (scanned exam papers, textbook MCQs) | Tesseract handles printed text well (~92%), so `OCR → DeepSeek` is a good fit |
| How to wire the scanned path? | **Hybrid** — `OCR → DeepSeek` first, **Gemini vision as fallback** | Free/cheap for the common printed case; quality never lost on the odd handwritten/bad scan |
| Which OCR engine? | **Open** — to be decided (leading candidate: **Tesseract, self-hosted**) | Depends on privacy vs zero-infra preference |

---

## 7. Recommended design (FDE recommendation)

**Hybrid, tiered — not a straight replacement:**

```
Scanned upload
   → Tesseract OCR (free, self-hosted, private)
        → is the extracted text solid? (enough length / confidence)
              ├─ YES → DeepSeek structures Q&A → review queue     (free path)
              └─ NO  → fall back to existing Gemini vision path    (safety net)
```

- **OCR engine:** **Tesseract**, self-hosted (lightweight, private, 1-line Docker
  add). Avoid EasyOCR/PaddleOCR (Railway weight) unless "good handwriting without
  Gemini" becomes a hard requirement. Avoid hosted OCR APIs unless we're
  comfortable sending student/exam content to a third party.
- **Structuring:** DeepSeek (existing key) reuses the **same extraction prompt**
  the platform already has (`extraction_prompts.EXTRACTION_SYSTEM`), so extracted
  questions flow through the exact same validation + review + publish path.
- **Fallback:** the current Gemini vision path stays as the automatic safety net.

This delivers "free OCR + DeepSeek" as envisioned, with Gemini only when OCR
can't cope.

---

## 8. Open questions / still to decide

1. **OCR engine + hosting:** Tesseract (self-hosted, private) vs OCR.space
   (hosted, zero-infra, data leaves)? *(Leaning Tesseract.)*
2. **The "is the OCR good enough?" threshold** that triggers the Gemini fallback
   (e.g. minimum characters per page, or a confidence signal).
3. **Multi-page scanned PDFs:** convert each page to an image (`pdf2image` +
   poppler) and OCR page-by-page, then merge — mirrors the existing chunking idea.
4. **Motivation confirmation:** is the driver cost, removing the Gemini
   dependency, or privacy/offline? (Affects whether the hybrid or a full replace
   is right.)

---

## 9. Implementation sketch (NOT yet built — for planning only)

- **Infra:** add `tesseract-ocr` + `poppler-utils` to the `Dockerfile`; add
  `pytesseract`, `pdf2image`, `Pillow` to `requirements.txt`.
- **Detection:** reuse the existing typed-vs-scanned check
  (`pdfplumber` text length threshold in `quiz_extraction.py`).
- **New OCR step:** for scanned input, render pages to images → Tesseract → raw
  text.
- **Structuring:** send the raw text through the existing text extraction path
  (`complete_json_with_fallback` with `EXTRACTION_SYSTEM`) — Gemini text or
  DeepSeek.
- **Fallback:** if OCR text is too thin/low-confidence, call the existing
  `gemini_json_multimodal` vision path.
- **No change** to the review/publish pipeline, the DB schema, or generation.

---

## 10. References

- PaddleOCR vs Tesseract vs EasyOCR — accuracy/speed/handwriting: https://www.codesota.com/ocr/paddleocr-vs-tesseract
- OCR comparison (Tesseract/EasyOCR/PaddleOCR/MMOCR): https://toon-beerten.medium.com/ocr-comparison-tesseract-versus-easyocr-vs-paddleocr-vs-mmocr-a362d9c79e66
- Best open-source OCR tools 2026: https://imagetotable.ai/blog/best-open-source-ocr-tools-2026
- Free OCR APIs & tiers (OCR.space, Google Vision): https://www.edenai.co/post/top-free-ocr-tools-apis-and-open-source-models
- Google Cloud Vision OCR pricing / free tier: https://lenscopy.com/compare/google-cloud-vision-ocr/
