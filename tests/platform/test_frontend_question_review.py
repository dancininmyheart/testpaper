from pathlib import Path


def test_question_review_text_does_not_render_image_url_placeholder():
    source = Path("frontend/src/pages/QuestionReview.tsx").read_text(encoding="utf-8")

    assert "[配图:" not in source
    assert "return ``;" not in source


def test_question_review_detail_boxes_use_adaptive_wrapping():
    source = Path("frontend/src/pages/QuestionReview.tsx").read_text(encoding="utf-8")

    assert "w-[clamp(320px,38vw,520px)]" in source
    assert "[overflow-wrap:anywhere]" in source
    assert "min-w-0 max-w-full" in source


def test_question_review_renders_latex_with_mathtext():
    review_source = Path("frontend/src/pages/QuestionReview.tsx").read_text(encoding="utf-8")
    math_source_path = Path("frontend/src/components/MathText.tsx")

    assert math_source_path.is_file()
    math_source = math_source_path.read_text(encoding="utf-8")
    assert "katex.renderToString" in math_source
    assert "import \"katex/dist/katex.min.css\"" in math_source
    assert "<MathText text={isMineru ? cleanContent(currentContent) : currentContent} />" in review_source


def test_question_review_allows_editing_question_content_before_approval():
    source = Path("frontend/src/pages/QuestionReview.tsx").read_text(encoding="utf-8")

    assert "draftQuestions" in source
    assert "updateQuestionContent" in source
    assert "<textarea" in source
    assert "approveMut.mutate(questions)" in source


def test_question_review_becomes_read_only_after_question_stage():
    source = Path("frontend/src/pages/QuestionReview.tsx").read_text(encoding="utf-8")

    assert "getProject" in source
    assert "isQuestionReviewEditable" in source
    assert 'project?.status === "review_questions"' in source
    assert "isQuestionReviewEditable &&" in source


def test_question_review_uses_larger_question_image_previews():
    source = Path("frontend/src/pages/QuestionReview.tsx").read_text(encoding="utf-8")

    assert "gap-3" in source
    assert "p-3" in source
    assert "h-[140px]" in source
    assert "w-[min(220px,100%)]" in source
    assert "object-contain" in source
