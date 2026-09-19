from app.services.topic_capacity import (
    selectable_topic_choices,
    suggested_question_limit,
    topic_choice_names,
)


def test_formula_capacity_supports_recall_rearrangement_and_application() -> None:
    assert suggested_question_limit({"formulas": [{"formula": "V = IR"}]}) == 3


def test_capacity_scales_with_subject_neutral_evidence() -> None:
    topic = {
        "key_definitions": [{"term": "A", "definition": "B"}],
        "key_facts_and_figures": ["fact one", "fact two"],
        "worked_examples": [{"full_example_text": "example"}],
    }
    assert suggested_question_limit(topic) == 5


def test_capacity_has_a_small_fallback_for_unstructured_topics() -> None:
    assert suggested_question_limit({"subtopics": ["A", "B"]}) == 2
    assert suggested_question_limit({}) == 1


def test_broad_science_parent_keeps_named_concepts_nested() -> None:
    choices = selectable_topic_choices([{
        "topic_name": "Electromagnetism",
        "subtopics": ["Ohm's Law", "Electric Power", "Coulomb's Law"],
        "formulas": [
            {"name": "Ohm's Law", "formula": "V = IR"},
            {"name": "Electric Power", "formula": "P = VI"},
            {"name": "Coulomb's Law", "formula": "F = k(q1q2)/r²"},
        ],
    }])

    assert [choice["name"] for choice in choices] == ["Electromagnetism"]
    assert choices[0]["subtopics"] == [
        "Ohm's Law", "Electric Power", "Coulomb's Law"
    ]
    assert choices[0]["suggested_question_limit"] == 9


def test_humanities_parent_keeps_independent_subtopics_as_preview() -> None:
    choices = selectable_topic_choices([{
        "topic_name": "French Revolution",
        "subtopics": ["Estates-General", "Reign of Terror", "Directory"],
    }])

    assert [choice["name"] for choice in choices] == ["French Revolution"]
    assert choices[0]["subtopics"] == [
        "Estates-General", "Reign of Terror", "Directory"
    ]


def test_source_names_are_preserved_as_child_preview() -> None:
    choices = selectable_topic_choices([{
        "topic_name": "Estates-General",
        "source_topic_names": ["Estates-General", "Reign of Terror", "Directory"],
    }])
    assert [choice["name"] for choice in choices] == ["Estates-General"]
    assert choices[0]["subtopics"] == ["Reign of Terror", "Directory"]


def test_focused_topic_remains_a_single_choice() -> None:
    topic = {
        "topic_name": "Photosynthesis",
        "subtopics": ["Chlorophyll"],
        "key_facts_and_figures": ["Plants convert light energy into chemical energy."],
    }
    assert selectable_topic_choices([topic]) == [{
        "name": "Photosynthesis",
        "subtopics": ["Chlorophyll"],
        "page_ranges": [],
        "suggested_question_limit": 1,
    }]
    assert topic_choice_names(topic) == {"photosynthesis", "chlorophyll"}


def test_definition_terms_do_not_become_hundreds_of_flat_choices() -> None:
    choices = selectable_topic_choices([{
        "topic_name": "Accounting Foundations",
        "key_definitions": [
            {"term": "Asset", "definition": "A resource controlled by an entity."},
            {"term": "Liability", "definition": "A present obligation."},
        ],
    }])
    assert [choice["name"] for choice in choices] == ["Accounting Foundations"]
    assert choices[0]["subtopics"] == []


def test_page_ranges_are_available_to_the_topic_picker() -> None:
    choices = selectable_topic_choices([{
        "topic_name": "Transport Layer",
        "source_page_ranges": [{"start": 120, "end": 145}],
    }])
    assert choices[0]["page_ranges"] == [{"start": 120, "end": 145}]
