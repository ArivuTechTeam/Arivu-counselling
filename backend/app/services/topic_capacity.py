"""Subject-neutral topic choices and conservative question-capacity estimates."""

from __future__ import annotations


def suggested_question_limit(topic: dict) -> int:
    """Estimate variety from distinct evidence, not page count or subject name.

    This is guidance rather than a hard generation limit. Formulas can support
    recall, rearrangement, and application; worked examples can support concept
    and application questions. Plain facts/definitions normally support one
    distinct assessment each.
    """
    definitions = len(topic.get("key_definitions") or [])
    facts = len(topic.get("key_facts_and_figures") or [])
    formulas = len(topic.get("formulas") or [])
    examples = len(topic.get("worked_examples") or [])
    structured_capacity = definitions + facts + (formulas * 3) + (examples * 2)
    if structured_capacity:
        return max(1, min(20, structured_capacity))

    fallback = len(topic.get("source_excerpts") or []) + len(topic.get("subtopics") or [])
    return max(1, min(20, fallback or 1))


_GENERIC_CHILD_NAMES = {
    "concept",
    "concepts",
    "definition",
    "definitions",
    "example",
    "examples",
    "formula",
    "formulas",
    "introduction",
    "overview",
}


def _usable_child_name(value: object, parent_name: str) -> str:
    name = " ".join(str(value or "").split()).strip(" -–—:;")
    if len(name) < 3:
        return ""
    folded = name.casefold()
    if folded == parent_name.casefold() or folded in _GENERIC_CHILD_NAMES:
        return ""
    return name


def topic_choice_names(topic: dict) -> set[str]:
    """Return every name that may legitimately select this source topic."""
    parent = " ".join(str(topic.get("topic_name") or "").split())
    names = {parent.casefold()} if parent else set()
    for value in topic.get("subtopics") or []:
        name = _usable_child_name(value, parent)
        if name:
            names.add(name.casefold())
    for value in topic.get("source_topic_names") or []:
        name = _usable_child_name(value, parent)
        if name:
            names.add(name.casefold())
    for formula in topic.get("formulas") or []:
        name = _usable_child_name(formula.get("name"), parent)
        if name:
            names.add(name.casefold())
    for definition in topic.get("key_definitions") or []:
        name = _usable_child_name(definition.get("term"), parent)
        if name:
            names.add(name.casefold())
    return names


def selectable_topic_choices(topics: list[dict]) -> list[dict]:
    """Expose a manageable list of major topics with child-concept previews.

    The complete hierarchy remains in the Master Blueprint.  Selection happens at
    the parent level so a long textbook does not turn hundreds of definitions,
    commands, formulas, and other micro-concepts into separate UI rows.
    """
    choices: dict[str, dict] = {}

    for topic in topics or []:
        parent = " ".join(str(topic.get("topic_name") or "").split())
        if not parent:
            continue

        children: dict[str, str] = {}
        for field in ("source_topic_names", "subtopics"):
            for value in topic.get(field) or []:
                name = _usable_child_name(value, parent)
                if name:
                    children.setdefault(name.casefold(), name)

        # Formula names are useful concept previews, but definition terms are
        # intentionally not promoted: long reference books can contain hundreds.
        for formula in topic.get("formulas") or []:
            name = _usable_child_name(formula.get("name"), parent)
            if name:
                children.setdefault(name.casefold(), name)

        ranges = [
            {"start": item.get("start"), "end": item.get("end")}
            for item in (topic.get("source_page_ranges") or [])
            if isinstance(item, dict) and item.get("start") and item.get("end")
        ]
        item = {
            "name": parent,
            "group_name": " ".join(str(topic.get("parent_group") or "").split()),
            "subtopics": list(children.values()),
            "page_ranges": ranges,
            "suggested_question_limit": suggested_question_limit(topic),
        }
        existing = choices.get(parent.casefold())
        if not existing:
            choices[parent.casefold()] = item
            continue

        existing["suggested_question_limit"] = max(
            existing["suggested_question_limit"], item["suggested_question_limit"]
        )
        known_children = {name.casefold() for name in existing["subtopics"]}
        existing["subtopics"].extend(
            name for name in item["subtopics"] if name.casefold() not in known_children
        )
        known_ranges = {(r["start"], r["end"]) for r in existing["page_ranges"]}
        existing["page_ranges"].extend(
            r for r in item["page_ranges"]
            if (r["start"], r["end"]) not in known_ranges
        )

    return list(choices.values())
