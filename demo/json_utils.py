from __future__ import annotations

import ast
import json
import re
import warnings
from typing import Any, Dict, List, Optional

from llm_knowledge_tagger import _extract_json_text, _loads_json_like, _strip_code_fences


def _extract_json_array_text(text: str) -> Optional[str]:
    match = re.search(r"\[.*\]", text, flags=re.S)
    if not match:
        return None
    return match.group(0)


def _safe_literal_eval(text: str) -> Any:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=SyntaxWarning)
        return ast.literal_eval(text)


def _loads_json_list_like(text: str) -> Optional[List[Dict[str, Any]]]:
    cleaned = _strip_code_fences(text)
    candidates = [cleaned]
    array_text = _extract_json_array_text(cleaned)
    object_text = _extract_json_text(cleaned)
    if array_text and array_text not in candidates and array_text != object_text:
        candidates.append(array_text)

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, list) and all(isinstance(item, dict) for item in data):
                return data
        except json.JSONDecodeError:
            pass
        try:
            data = _safe_literal_eval(candidate)
            if isinstance(data, list) and all(isinstance(item, dict) for item in data):
                return data
        except (ValueError, SyntaxError):
            pass
    return None


def _loads_json_object_like(text: str) -> Optional[Dict[str, Any]]:
    cleaned = _strip_code_fences(text)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    try:
        data = _safe_literal_eval(cleaned)
        if isinstance(data, dict):
            return data
    except (ValueError, SyntaxError):
        pass

    first_object = cleaned.find("{")
    first_array = cleaned.find("[")
    if first_object != -1 and (first_array == -1 or first_object < first_array):
        return _loads_json_like(cleaned)
    return None


def _normalize_llm_json_payload(text: str, *, expected_list_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    data = _loads_json_object_like(text)
    if isinstance(data, dict):
        if isinstance(expected_list_key, str) and expected_list_key:
            normalized = _normalize_expected_list_payload(data, expected_list_key)
            if isinstance(normalized, dict):
                return normalized
        return data
    if isinstance(expected_list_key, str) and expected_list_key:
        list_data = _loads_json_list_like(text)
        if list_data is not None:
            return {expected_list_key: list_data}
    return None


def _normalize_expected_list_payload(data: Dict[str, Any], expected_list_key: str) -> Optional[Dict[str, Any]]:
    if isinstance(data.get(expected_list_key), list):
        return data
    aliases_by_key: Dict[str, List[str]] = {
        "questions": ["question", "items", "results", "data"],
        "answers": ["answer", "items", "results", "data"],
        "reference_answers": ["references", "reference", "answers", "items", "results", "data"],
        "items": ["results", "data", "outputs", "output"],
    }
    candidate_keys = aliases_by_key.get(expected_list_key, ["items", "results", "data"])
    for key in candidate_keys:
        value = data.get(key)
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            normalized = dict(data)
            normalized[expected_list_key] = value
            return normalized
        if isinstance(value, dict):
            nested = _normalize_expected_list_payload(value, expected_list_key)
            if isinstance(nested, dict) and isinstance(nested.get(expected_list_key), list):
                normalized = dict(data)
                normalized[expected_list_key] = nested[expected_list_key]
                return normalized
    return None


def _is_llm_json_payload_error(exc: Exception) -> bool:
    message = str(exc).strip().lower()
    if not message:
        return False
    if "valid json object" in message:
        return True
    if "jsondecodeerror" in message:
        return True
    return "json" in message and "did not return" in message
