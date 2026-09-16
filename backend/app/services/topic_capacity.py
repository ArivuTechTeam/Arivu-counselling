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
    return max(1, min(6, fallback or 1))


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
    """Expose independently assessable concepts instead of broad containers.

    The extraction blueprint intentionally retains hierarchy and evidence under a
    broad parent. Teachers, however, need to select the leaves they want tested.
    When a parent contains two or more named children, promote those children to
    selectable choices. A focused topic remains unchanged.
    """
    choices: dict[str, dict] = {}

    def add(name: str, capacity_source: dict) -> None:
        key = name.casefold()
        limit = suggested_question_limit(capacity_source)
        existing = choices.get(key)
        if existing:
            existing["suggested_question_limit"] = max(
                existing["suggested_question_limit"], limit
            )
            return
        choices[key] = {"name": name, "suggested_question_limit": limit}

    for topic in topics or []:
        parent = " ".join(str(topic.get("topic_name") or "").split())
        if not parent:
            continue

        children: dict[str, dict] = {}

        def child(name: str) -> dict:
            return children.setdefault(name.casefold(), {"name": name})

        for value in topic.get("source_topic_names") or []:
            name = " ".join(str(value or "").split()).strip(" -–—:;")
            if len(name) >= 3 and name.casefold() not in _GENERIC_CHILD_NAMES:
                child(name).setdefault("subtopics", []).append(name)

        for value in topic.get("subtopics") or []:
            name = _usable_child_name(value, parent)
            if name:
                child(name).setdefault("subtopics", []).append(name)

        for formula in topic.get("formulas") or []:
            name = _usable_child_name(formula.get("name"), parent)
            if name:
                child(name).setdefault("formulas", []).append(formula)

        # Definition terms are useful fallbacks for non-quantitative subjects
        # when the model supplied no explicit subtopic/formula hierarchy.
        if not children:
            for definition in topic.get("key_definitions") or []:
                name = _usable_child_name(definition.get("term"), parent)
                if name:
                    child(name).setdefault("key_definitions", []).append(definition)

        if len(children) >= 2:
            for item in children.values():
                add(item.pop("name"), item)
        else:
            add(parent, topic)

    return list(choices.values())
