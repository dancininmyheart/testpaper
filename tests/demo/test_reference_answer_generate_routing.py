from __future__ import annotations

from demo.service import DemoService, _normalize_reference_answer_item


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
