from __future__ import annotations

from backend.application.paper_service import PaperService


class _FakePaperRepo:
    def get_question_images(self, project_id: str):
        assert project_id == "project_1"
        return [
            {
                "question_id": "Q1",
                "file_id": 10,
                "file_name": "diagram.png",
                "local_path": "diagram-path",
                "content_type": "image/png",
                "page_index": 0,
                "sort_order": 0,
            }
        ]


class _FakeStorage:
    def read_bytes(self, local_path: str) -> bytes:
        assert local_path == "diagram-path"
        return b"diagram-image-bytes"


def test_attach_question_images_encodes_question_images_for_reference_generation():
    service = PaperService(
        paper_repo=_FakePaperRepo(),
        storage=_FakeStorage(),
        audit=None,
        state_service=None,
    )

    questions = service._attach_question_images(
        project_id="project_1",
        questions=[{"question_id": "Q1", "content": "reviewed question"}],
    )

    assert questions[0]["content"] == "reviewed question"
    assert questions[0]["question_image_urls"] == [
        "data:image/png;base64,ZGlhZ3JhbS1pbWFnZS1ieXRlcw=="
    ]
    assert questions[0]["question_images"][0]["file_name"] == "diagram.png"
