"""
QuizGeneratorService — the final step of large-document quiz generation.

Once the analysis job is ready, its Master Blueprint (the consolidated, de-duped
study content) is the source material for a SINGLE generation call — the same
question writer + persistence the small-document blueprint path uses. Feeding the
compact blueprint instead of the raw 200-page text is exactly what keeps this one
call within the model's output budget with no truncation.

Flow: teacher picks topics from the blueprint (with High/Med/Low weights) ->
render the blueprint to text -> generate + persist -> link the new quiz_set back
to the job -> normal teacher review + publish.
"""

from __future__ import annotations

from collections.abc import Callable

from app.lib.auth import CurrentProfile
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.blueprint import generate_and_persist_from_material
from app.services.teacher_access import teacher_has_subject
from app.services.topic_capacity import topic_choice_names


def render_blueprint_material(
    blueprint: dict, selected_topic_names: set[str] | None = None
) -> str:
    """Render a Master Blueprint's topics into a compact study-material text block
    for the question writer. Verbatim content is preserved; the structure just
    makes topic boundaries explicit so questions can be tagged to a topic."""
    lines: list[str] = []
    for topic in blueprint.get("topics", []) or []:
        name = str(topic.get("topic_name", "")).strip()
        if not name:
            continue
        if selected_topic_names is not None and not (
            topic_choice_names(topic) & selected_topic_names
        ):
            continue
        lines.append(f"## {name}")
        ranges = topic.get("source_page_ranges") or []
        if ranges:
            rendered_ranges = ", ".join(
                f"{r.get('start')}-{r.get('end')}"
                for r in ranges
                if isinstance(r, dict) and r.get("start") and r.get("end")
            )
            if rendered_ranges:
                lines.append(f"Approximate source pages: {rendered_ranges}")
        subs = [s for s in (topic.get("subtopics") or []) if s]
        if subs:
            lines.append("Subtopics: " + ", ".join(subs))
        for d in topic.get("key_definitions") or []:
            term, definition = d.get("term"), d.get("definition")
            if term and definition:
                lines.append(f"- Definition — {term}: {definition}")
        for fact in topic.get("key_facts_and_figures") or []:
            if fact:
                lines.append(f"- Fact: {fact}")
        for f in topic.get("formulas") or []:
            if f.get("formula"):
                extra = f" ({f['variables_explained']})" if f.get("variables_explained") else ""
                lines.append(f"- Formula — {f.get('name', '')}: {f['formula']}{extra}")
        for w in topic.get("worked_examples") or []:
            body = w.get("full_example_text") or w.get("description")
            if body:
                lines.append(f"- Worked example: {body}")
        for excerpt in topic.get("source_excerpts") or []:
            body = str(excerpt.get("text") or "").strip()
            if body:
                lines.append(f'- Source excerpt: "{" ".join(body.split())}"')
        lines.append("")
    return "\n".join(lines).strip()


class QuizGeneratorService:
    def __init__(self, service=None) -> None:
        self._service = service

    @property
    def _client(self):
        return self._service or get_service_client()

    def _load_ready_job(self, job_id: str, profile: CurrentProfile) -> dict:
        res = (
            self._client.table("quiz_generation_jobs")
            .select("*")
            .eq("id", job_id)
            .eq("tenant_id", profile.tenant_id)
            .eq("created_by", profile.user_id)
            .maybe_single()
            .execute()
        )
        job = res.data if res and res.data else None
        if not job:
            raise ValueError("Generation job not found.")
        if job.get("status") != "completed" or not job.get("master_blueprint"):
            raise ValueError("This document's analysis isn't ready yet.")
        return job

    def generate_from_job(
        self,
        *,
        job_id: str,
        subject_id: str,
        chapter_name: str,
        selected_topics: list[dict],
        total_questions: int,
        question_types: list[str],
        cognitive_level: str,
        difficulty: str,
        profile: CurrentProfile,
        type_counts: dict[str, int] | None = None,
        persist_result: Callable[[dict], dict] | None = None,
    ) -> dict:
        service = self._client
        job = self._load_ready_job(job_id, profile)

        # Same access rule as the small-doc path: explicit subject assignment.
        if not teacher_has_subject(service, profile, subject_id):
            raise ValueError("Subject not found.")

        requested_names = {
            str(topic.get("name") or "").strip().casefold()
            for topic in selected_topics
            if str(topic.get("name") or "").strip()
        }
        if not requested_names:
            raise ValueError("Select at least one extracted topic before generating.")

        # Accept both currently exposed leaf choices and their parent names so a
        # page opened before an analysis/UI update does not become invalid.
        available_names: set[str] = set()
        for topic in job["master_blueprint"].get("topics") or []:
            available_names.update(topic_choice_names(topic))
        missing_names = requested_names - available_names
        if missing_names:
            raise ValueError("One or more selected topics are not in the completed analysis.")

        material = render_blueprint_material(job["master_blueprint"], requested_names)
        if not material:
            raise ValueError("The analysis produced no usable content to generate from.")
        if len(material) > get_settings().generation_max_text_chars:
            raise ValueError(
                "The selected topics contain too much source material for one safe "
                "generation call. Select fewer topics and try again."
            )

        persistence_options = {"persist_result": persist_result} if persist_result else {}
        result = generate_and_persist_from_material(
            service=service,
            tenant_id=profile.tenant_id,
            material=material,
            subject_id=subject_id,
            chapter_name=chapter_name,
            selected_topics=selected_topics,
            total_questions=total_questions,
            question_types=question_types,
            cognitive_level=cognitive_level,
            difficulty=difficulty,
            profile=profile,
            type_counts=type_counts,
            selected_only_material=True,
            source_document_id=job["document_id"],
            **persistence_options,
        )

        if persist_result is not None:
            # The transactional worker commit also links the analysis job.
            return result

        # Link the created quiz set back to the job (best-effort; non-fatal).
        quiz_set_id = result.get("quiz_set_id")
        if quiz_set_id:
            job_params = {
                **(job.get("params") or {}),
                "selected_topics": selected_topics,
            }
            service.table("quiz_generation_jobs").update(
                {"quiz_set_id": quiz_set_id, "subject_id": subject_id,
                 "chapter_name": chapter_name, "params": job_params}
            ).eq("id", job_id).eq("tenant_id", profile.tenant_id).execute()
        result["job_id"] = job_id
        result["source_material_chars"] = len(material)
        return result
