from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _iter_json_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    for file_path in sorted(path.rglob("*.json")):
        if file_path.is_file():
            yield file_path


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sample_id_from_payload(payload: Any, file_path: Path) -> str:
    if isinstance(payload, dict):
        student_id = payload.get("student_id")
        if isinstance(student_id, str) and student_id.strip():
            return student_id.strip()
    return file_path.stem


def _extract_records(payload: Any, file_path: Path) -> List[Dict[str, Any]]:
    sample_id = _sample_id_from_payload(payload, file_path)
    if isinstance(payload, dict) and isinstance(payload.get("answer_trace"), list):
        raw_records = payload["answer_trace"]
    elif isinstance(payload, list):
        raw_records = payload
    else:
        raw_records = []

    records: List[Dict[str, Any]] = []
    for item in raw_records:
        if not isinstance(item, dict):
            continue
        question_id = item.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            continue
        sub_question_id = item.get("sub_question_id") if isinstance(item.get("sub_question_id"), str) else ""
        score = item.get("score") if isinstance(item.get("score"), (int, float)) else None
        max_score = item.get("max_score") if isinstance(item.get("max_score"), (int, float)) else None
        answer_page_side = item.get("answer_page_side") if isinstance(item.get("answer_page_side"), str) else None
        records.append(
            {
                "sample_id": sample_id,
                "question_id": question_id.strip(),
                "sub_question_id": sub_question_id.strip(),
                "score": score,
                "max_score": max_score,
                "answer_page_side": answer_page_side,
            }
        )
    return records


def _load_record_index(path: Path) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    index: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for file_path in _iter_json_files(path):
        payload = _load_json(file_path)
        for record in _extract_records(payload, file_path):
            key = (
                record["sample_id"],
                record["question_id"],
                record["sub_question_id"],
            )
            index[key] = record
    return index

def _question_num(question_id: str) -> int | None:
    match = re.fullmatch(r"Q(\d{1,3})", question_id.strip())
    if not match:
        return None
    return int(match.group(1))


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate question/score extraction accuracy.")
    parser.add_argument("--gold", required=True, help="Gold JSON file or directory.")
    parser.add_argument("--pred", required=True, help="Prediction JSON file or directory.")
    args = parser.parse_args()

    gold_index = _load_record_index(Path(args.gold))
    pred_index = _load_record_index(Path(args.pred))
    if not gold_index:
        raise SystemExit("No gold records found.")
    if not pred_index:
        raise SystemExit("No prediction records found.")

    total = len(gold_index)
    qid_match = 0
    score_match = 0
    score_pair_match = 0
    adjacent_confusions = 0

    pred_by_sample: Dict[str, List[Dict[str, Any]]] = {}
    for record in pred_index.values():
        pred_by_sample.setdefault(record["sample_id"], []).append(record)

    for key, gold in gold_index.items():
        pred = pred_index.get(key)
        if pred is not None:
            qid_match += 1
            if pred.get("score") == gold.get("score"):
                score_match += 1
            if pred.get("score") == gold.get("score") and pred.get("max_score") == gold.get("max_score"):
                score_pair_match += 1
            continue

        gold_num = _question_num(gold["question_id"])
        if gold_num is None:
            continue
        sample_records = pred_by_sample.get(gold["sample_id"], [])
        for candidate in sample_records:
            cand_num = _question_num(candidate["question_id"])
            if cand_num is None or abs(cand_num - gold_num) != 1:
                continue
            if candidate.get("score") == gold.get("score") and candidate.get("max_score") == gold.get("max_score"):
                adjacent_confusions += 1
                break

    print(f"gold_records={total}")
    print(f"question_exact_match={qid_match / total:.4f}")
    print(f"score_exact_match={score_match / total:.4f}")
    print(f"score_pair_exact_match={score_pair_match / total:.4f}")
    print(f"adjacent_question_confusion_rate={adjacent_confusions / total:.4f}")


