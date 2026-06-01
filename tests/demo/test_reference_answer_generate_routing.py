from __future__ import annotations

from demo.service import (
    DemoService,
    _group_contexts_by_answer_key_page,
    _normalize_reference_answer_item,
)


def test_reference_answer_generate_routes_text_items_to_text_profile_and_image_items_to_vision_profile():
    service = DemoService.__new__(DemoService)
    service.reference_answer_chunk_size = 8
    service.question_chunk_size = 8
    service.answer_concurrency = 4
    service.profile = {"profile_name": "vision"}
    service.text_profile = {"profile_name": "text"}
    service._log_progress = lambda *args, **kwargs: None

    calls = []

    def fake_common(**kwargs):
        calls.append(kwargs)
        return [
            {
                "question_id": item["question_id"],
                "reference_answer_text": f"answer for {item['question_id']}",
                "confidence": 0.9,
            }
            for item in kwargs["answer_contexts"]
        ]

    service._run_reference_answer_common = fake_common

    image_url = "data:image/png;base64,aW1hZ2U="
    answers = service._run_reference_answer_generate(
        answer_contexts=[
            {
                "question_id": "Q1",
                "question_type": "solution",
                "problem_text": "text-only question",
            },
            {
                "question_id": "Q2",
                "question_type": "solution",
                "problem_text": "diagram question",
                "question_image_urls": [image_url],
            },
        ],
        paper_urls=["data:image/png;base64,cGFnZQ=="],
        warnings=[],
    )

    assert {item["question_id"] for item in answers} == {"Q1", "Q2"}
    assert len(calls) == 2

    text_call = next(call for call in calls if call["answer_contexts"][0]["question_id"] == "Q1")
    vision_call = next(call for call in calls if call["answer_contexts"][0]["question_id"] == "Q2")
    assert text_call["profile"] == {"profile_name": "text"}
    assert text_call["data_urls"] == []
    assert vision_call["profile"] == {"profile_name": "vision"}
    assert vision_call["data_urls"] == [image_url]


def test_reference_answer_generate_sends_one_question_per_parallel_call():
    service = DemoService.__new__(DemoService)
    service.reference_answer_chunk_size = 8
    service.question_chunk_size = 8
    service.answer_concurrency = 4
    service.profile = {"profile_name": "vision"}
    service.text_profile = {"profile_name": "text"}
    service._log_progress = lambda *args, **kwargs: None

    calls = []

    def fake_common(**kwargs):
        calls.append(kwargs)
        contexts = kwargs["answer_contexts"]
        assert len(contexts) == 1
        return [
            {
                "question_id": contexts[0]["question_id"],
                "reference_answer_text": f"answer for {contexts[0]['question_id']}",
                "confidence": 0.9,
            }
        ]

    service._run_reference_answer_common = fake_common

    answers = service._run_reference_answer_generate(
        answer_contexts=[
            {"question_id": "Q1", "question_type": "choice", "problem_text": "first"},
            {"question_id": "Q2", "question_type": "choice", "problem_text": "second"},
            {"question_id": "Q3", "question_type": "choice", "problem_text": "third"},
        ],
        paper_urls=[],
        warnings=[],
    )

    assert [call["answer_contexts"][0]["question_id"] for call in calls] == ["Q1", "Q2", "Q3"]
    assert {item["question_id"] for item in answers} == {"Q1", "Q2", "Q3"}


def test_reference_answer_single_question_normalization_uses_target_question_id():
    parsed = _normalize_reference_answer_item(
        {
            "question_id": "Q99",
            "reference_answer_text": "target answer",
            "reference_final_answer": "A",
            "reference_steps": ["step"],
        },
        {
            "Q1": {
                "question_id": "Q1",
                "question_type": "choice",
                "problem_text": "target question",
            }
        },
    )

    assert parsed is not None
    assert parsed["question_id"] == "Q1"
    assert parsed["reference_final_answer"] == "A"


def test_prepare_reference_answers_generates_missing_uploaded_items():
    service = DemoService.__new__(DemoService)
    service._log_progress = lambda *args, **kwargs: None

    generated_calls = []

    def fake_generate(**kwargs):
        generated_calls.append(kwargs)
        return [
            {
                "question_id": item["question_id"],
                "reference_answer_text": f"generated {item['question_id']}",
                "source": "generated",
            }
            for item in kwargs["answer_contexts"]
        ]

    service._run_reference_answer_extract_via_mineru = lambda **kwargs: [
        {
            "question_id": "Q1",
            "reference_answer_text": "uploaded Q1",
            "source": "uploaded",
        }
    ]
    service._run_reference_answer_generate = fake_generate

    answers, source = service._prepare_reference_answers(
        answer_key_urls=["answer-page-1"],
        answer_contexts=[
            {"question_id": "Q1", "question_type": "choice", "problem_text": "first"},
            {"question_id": "Q2", "question_type": "choice", "problem_text": "second"},
            {"question_id": "Q3", "question_type": "choice", "problem_text": "third"},
        ],
        paper_urls=["paper-page-1"],
        preferred_source="uploaded",
        warnings=[],
    )

    assert source == "uploaded"
    assert {item["question_id"] for item in answers} == {"Q1", "Q2", "Q3"}
    assert [item["question_id"] for item in generated_calls[0]["answer_contexts"]] == ["Q2", "Q3"]


def test_group_contexts_by_answer_key_page_distributes_unhinted_contexts():
    grouped = _group_contexts_by_answer_key_page(
        [
            {"question_id": "Q1", "question_order_index": 0},
            {"question_id": "Q2", "question_order_index": 1},
            {"question_id": "Q3", "question_order_index": 2},
            {"question_id": "Q4", "question_order_index": 3},
        ],
        page_count=2,
    )

    assert [item["question_id"] for item in grouped[0]] == ["Q1", "Q2"]
    assert [item["question_id"] for item in grouped[1]] == ["Q3", "Q4"]
