# Quiz Generation Direction

**Status:** working direction note  
**Date:** August 6, 2026  
**Purpose:** explain where the quiz-generation system should go next, why the current model is limited, and why we should avoid adding LangChain or LangGraph right now.

---

## 1. Why this document exists

The current project already has a working path for:

1. teacher uploads a document
2. system extracts text
3. system sends text + quiz settings to an LLM
4. LLM returns questions
5. teacher reviews and publishes

That is a valid MVP path. It proves that the platform can ingest educational material and produce draft quizzes.

But there is an important product-quality problem:

If we stop at "send PDF text to model and get questions back", the output will often feel generic, shallow, and only loosely aligned with what a faculty member actually wants.

This document explains:

- what the current system is doing
- where it will fail in real faculty use
- what the next-quality layer should be
- why the right next step is better product structure, not more AI framework complexity

---

## 2. Current state of the system

Today, the generation flow is conceptually simple:

1. extract text from uploaded PDF or DOCX
2. take a window of that text
3. build a prompt using selected options
4. call the model
5. validate JSON
6. store the generated questions for review

This is a direct generation pipeline.

That is good for:

- proving end-to-end functionality
- moving fast
- validating whether teachers find the review workflow useful
- keeping the code understandable

That is not yet good for:

- topic-aware quiz construction
- faculty-specific teaching style
- chapter weightage
- exam-pattern alignment
- controlled difficulty distribution
- curriculum-aware coverage

So the current system is useful as a first slice, but not yet strong enough to be the final generation model.

---

## 3. The main product risk: generic AI output

If the app simply asks an LLM:

"Here is some extracted text. Generate a quiz."

the model will usually do what LLMs do by default:

- produce balanced-looking output
- overuse easy factual questions
- sample from whatever text is most visible
- claim difficulty labels without true calibration
- sound educational without being tightly aligned to the teacher's intent

This is the core risk.

The result may look acceptable on first read, but a serious faculty member will often notice that it is not actually designed the way they would design a quiz.

The issue is not that the model is useless.

The issue is that the model does not know, on its own:

- which chapters matter more
- which topics are repeatedly emphasized in class
- which topics are low priority
- whether the teacher wants recall-heavy or application-heavy questions
- whether the institution prefers conceptual framing or exam-style framing
- how the teacher wants marks distributed
- what kind of weak questions the teacher dislikes

Without that structure, the model fills in the gaps with generic patterns.

That is what makes AI output feel like "slop": not necessarily wrong, but not grounded in instructional intent.

---

## 4. What faculty actually wants

Faculty usually does not want:

- random questions from a chapter
- equal treatment of all visible topics
- generic textbook paraphrasing

Faculty usually wants some controlled combination of:

- topic importance
- chapter weightage
- exam relevance
- theory vs practical balance
- easy / medium / hard distribution
- institution-specific style
- questions that match how they teach
- exclusion of low-value content
- emphasis on repeated pain points for students

In other words, the real product is not just question generation.

The real product is controlled quiz composition.

The LLM is only one component inside that system.

---

## 5. The correct mental model

We should think about the system this way:

- the platform decides what the quiz should contain
- the model writes the actual questions

That is a much better design than asking the model to decide everything.

Said differently:

- the app should behave like the exam setter
- the model should behave like the question writer

If we let the model act as both exam setter and question writer, we get convenience, but we also get weak control and uneven quality.

If the app controls the blueprint and the model fills it in, the output becomes much more faculty-aligned.

---

## 6. Where the system should go next

The next layer should not be "more advanced prompting" alone.

The next layer should be structured instructional control.

The most important additions are below.

### 6.1 Topic-aware content structure

The system should move away from treating the uploaded document as one large text body.

Instead, it should identify and work with:

- course
- subject
- chapter
- topic
- section or subtopic when useful

This can begin with imperfect automatic extraction, as long as the teacher can review and correct it.

Why this matters:

- generation becomes targeted instead of broad
- coverage becomes measurable
- weightage becomes possible
- quiz analytics become meaningful

### 6.2 Weightage-driven generation

Each chapter or topic should be allowed to carry relative importance.

Examples:

- Capital budgeting: 30%
- Ratio analysis: 20%
- Cash flow basics: 10%
- Theory definitions: 5%

This allows the quiz to reflect what actually matters in teaching and in exams.

Why this matters:

- not all content deserves equal presence
- faculty thinks in importance, not text volume
- the PDF's page count should not decide quiz composition

### 6.3 Quiz blueprint before generation

Before the model generates anything, the system should know the intended structure of the quiz.

A blueprint should describe at least:

- total number of questions
- marks per question or total marks
- question-type mix
- difficulty mix
- cognitive-level mix
- topic allocation
- optional exclusions
- optional style constraints

Example blueprint:

- 20 questions total
- 40% from Topic A
- 30% from Topic B
- 20% from Topic C
- 10% from Topic D
- 50% medium, 30% hard, 20% easy
- mostly practical, some theory-to-practical
- avoid trivial definition-only questions

At that point, generation is no longer vague. It becomes intentional.

### 6.4 Teacher-controlled preferences

Different faculty members prefer different question styles.

Some prefer:

- direct exam-style questions
- compact wording
- strict grading logic
- more problem-solving

Others prefer:

- conceptual questions
- explanatory language
- gradual difficulty
- more theory recall

The system should eventually learn and store teacher preferences rather than treating every generation request as isolated.

### 6.5 Feedback loop from review behavior

Teacher review is not only a quality gate. It is training signal for product quality.

If a teacher repeatedly:

- rejects definition-only questions
- edits questions to be shorter
- approves numerical problems more often
- removes weak distractors

the system should use that signal later.

Even simple analytics would help:

- approval rate by question type
- approval rate by topic
- approval rate by provider
- edit frequency by difficulty level

This is one of the strongest long-term assets in the product.

---

## 7. A better generation architecture

The next version of generation should look more like this:

1. teacher uploads material
2. system extracts text
3. system identifies candidate chapter/topic structure
4. teacher reviews or edits topic map
5. teacher sets weightage and generation preferences
6. system builds a quiz blueprint
7. system selects the relevant topic chunks
8. system asks the model to generate questions for specific slots in the blueprint
9. system validates output
10. teacher reviews and publishes

This is still a practical system. It is not overengineered.

It simply moves the control point earlier in the pipeline.

---

## 8. What should stay simple right now

It is important not to overreact and rebuild everything at once.

Right now we do not need:

- a complex multi-agent architecture
- graph orchestration just because AI frameworks make it possible
- advanced retrieval infrastructure before we have stable topic control
- semantic search for every generation path
- a highly abstract AI platform layer

We should keep the following simple:

- direct service-layer orchestration in Python
- explicit prompt-building code
- explicit validation code
- explicit storage logic
- explicit retry/fallback logic

That keeps the system understandable and easier to debug.

---

## 9. Why we should not add LangChain now

LangChain can be useful, but it is not the right next move for this project.

### 9.1 What LangChain could help with later

It can help with:

- document loaders
- chunking pipelines
- output parsers
- retrieval patterns
- provider abstraction
- reusable prompt chains

Those are real benefits in some systems.

### 9.2 Why it is not needed now

Our current bottleneck is not lack of framework tooling.

Our real bottleneck is lack of instructional structure:

- topic modeling
- weightage
- blueprint control
- review feedback usage

LangChain does not solve those product decisions for us.

If we add it now, we mainly add:

- one more abstraction layer
- more framework-specific behavior to learn
- more debugging complexity
- more cognitive load during an already-early product phase

For a system that still needs core product rules clarified, this is the wrong trade.

### 9.3 The practical conclusion on LangChain

Do not add LangChain now.

Reconsider it only if later we clearly need:

- richer retrieval pipelines
- standardized chunk/loader components
- repeated prompt-chain patterns that have become noisy in plain Python

Until then, plain Python service code is the better engineering choice.

---

## 10. Why we should not add LangGraph now

LangGraph is even less necessary right now than LangChain.

### 10.1 What LangGraph is good at

LangGraph becomes useful when generation is a real workflow graph with:

- branching
- retries
- human-in-the-loop checkpoints
- stateful multi-step flows
- partial recovery
- conditional routing between nodes

For example:

- detect document type
- split into topics
- classify content quality
- choose strategy
- generate per slot
- self-evaluate
- regenerate failed slots
- escalate to human review

That is a good fit for graph orchestration.

### 10.2 Why it is not the right next step

Today, our generation flow is still small enough to express clearly in ordinary service code.

If we adopt LangGraph too early, we risk:

- solving orchestration complexity we do not yet have
- building around framework concepts before product logic is stable
- making the project harder for the team to reason about
- increasing the chance of "clever AI architecture" before strong educational behavior

The problem in front of us is not graph orchestration.

The problem is quiz design quality.

### 10.3 The practical conclusion on LangGraph

Do not add LangGraph now.

Consider it later only if the pipeline genuinely becomes:

- multi-step
- branching
- stateful
- hard to maintain in normal Python

That may happen in the future. It is not necessary now.

---

## 11. What we should build before any AI framework adoption

The next product and engineering focus should be:

### 11.1 Product-level controls

- teacher-confirmable chapter/topic structure
- topic weightage controls
- difficulty mix controls
- cognitive-level mix controls
- question-type mix controls
- exclusions for unimportant content

### 11.2 Better generation internals

- chunk storage by chapter/topic
- better material selection per generation request
- slot-based generation from a blueprint
- output validation per slot
- targeted retry when a question is malformed or weak

### 11.3 Review intelligence

- track approvals, edits, rejections
- track weak question patterns
- capture faculty-specific preferences over time

### 11.4 Operational safety

- stronger tests around grading and generation contracts
- clearer provider behavior and fallback rules
- tighter handling of scanned PDFs and low-text documents

These are much higher-value investments than adding framework complexity right now.

---

## 12. A good phased direction

The cleanest path forward is to evolve in phases.

### Phase A: stabilize current MVP

Goal:

- make the current upload -> generate -> review -> publish flow reliable

Focus:

- output quality improvements
- validation
- error handling
- review ergonomics
- grading correctness

### Phase B: add instructional structure

Goal:

- stop generating from "big text blob" thinking

Focus:

- chapter/topic extraction
- topic confirmation UI
- topic-linked storage
- topic-aware generation

### Phase C: add controlled quiz composition

Goal:

- make quiz generation faculty-driven rather than model-driven

Focus:

- weightage
- quiz blueprint
- distribution controls
- slot-based generation

### Phase D: add preference learning

Goal:

- make the system adapt to teacher behavior

Focus:

- review analytics
- approval/edit/reject feedback
- faculty profiles and defaults

### Phase E: reconsider framework support

Only here should we seriously ask:

- is plain Python orchestration becoming too messy?
- do we need graph/state orchestration?
- do we need richer retrieval tooling?

If yes, then evaluate LangChain or LangGraph based on the specific problem, not because they are popular.

---

## 13. Final recommendation

The current system is a good MVP foundation, but if it remains a one-step "PDF in, quiz out" pipeline, a lot of output will feel generic.

The right next step is not adding LangChain or LangGraph.

The right next step is making the system more educationally structured:

- understand chapters and topics
- let faculty express importance and intent
- generate from a blueprint
- learn from review behavior

This will improve product quality far more than adding AI orchestration frameworks right now.

Plain Python services are still the right implementation approach at this stage.

We should only introduce LangChain or LangGraph later if a real, concrete maintenance problem appears that those tools solve better than our current code.

That keeps the project focused on the real problem:

building a quiz system that faculty trusts, not just a system that can call a model.

---

## 14. Short version

If we do only:

- extract text
- prompt model
- return quiz

we will get usable output sometimes, but often generic output.

If we instead do:

- identify topics
- assign weightage
- build a quiz blueprint
- generate per blueprint slot
- learn from teacher review

we move from generic AI generation to faculty-aligned quiz construction.

That is the direction worth building toward.
