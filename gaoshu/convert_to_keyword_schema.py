from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

NODE_TYPES = ["concept", "formula", "method", "theorem", "skill"]
SKIP_TITLE_PATTERNS = (
    "习题",
    "总练习题",
    "习题答案",
    "答案与提示",
    "附录",
)


def _is_keyword_schema(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("nodes"), list)


def _load_json(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8-sig")
    decoder = json.JSONDecoder()
    idx = 0
    values: List[Any] = []
    length = len(raw)
    while idx < length:
        while idx < length and raw[idx].isspace():
            idx += 1
        if idx >= length:
            break
        value, end = decoder.raw_decode(raw, idx)
        values.append(value)
        idx = end
    if not values:
        raise ValueError(f"empty json file: {path}")
    if len(values) == 1:
        return values[0]
    if all(isinstance(item, list) for item in values):
        merged: List[Any] = []
        for item in values:
            merged.extend(item)
        return merged
    return values[0]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean_title(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    s = text.strip()
    s = s.lstrip("*")
    s = re.sub(r"^\d+(?:\.\d+)*\s*", "", s)
    s = re.sub(r"^[一二三四五六七八九十]+[、.]\s*", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_noise_title(title: str) -> bool:
    if not title:
        return True
    return any(token in title for token in SKIP_TITLE_PATTERNS)


def _edition_from_filename(path: Path) -> str:
    name = path.stem.upper()
    if "A" in name:
        return "A"
    if "B" in name:
        return "B"
    return "GEN"


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", text)
    cleaned = cleaned.strip("-").lower()
    return cleaned or "item"


def _split_id_tokens(raw_id: Any) -> List[str]:
    if not isinstance(raw_id, str):
        return []
    text = raw_id.strip().lower()
    if not text:
        return []
    if re.fullmatch(r"\d+(?:\.\d+)*", text):
        return [f"n{part}" for part in text.split(".") if part]
    token = _slug(text)
    return [token] if token else []


def _node_type_from_outline_type(outline_type: str) -> str:
    mapping = {
        "chapter": "concept",
        "section": "concept",
        "subsection": "skill",
        "appendix": "concept",
    }
    return mapping.get(outline_type, "concept")


def _node_id(
    *,
    edition: str,
    chapter_token: str,
    path_tokens: List[str],
    title: str,
    fallback_index: int,
) -> str:
    base = [f"gaoshu.{edition.lower()}", chapter_token]
    if path_tokens:
        base.extend(path_tokens)
    else:
        base.append(f"idx{fallback_index}")
    title_token = _slug(title)
    if title_token:
        base.append(title_token)
    return ".".join(part for part in base if part)


def _iter_outline(
    items: List[Dict[str, Any]],
    *,
    edition: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, List[str]]]]:
    nodes: List[Dict[str, Any]] = []
    taxonomy: Dict[str, Dict[str, List[str]]] = {f"高等数学{edition}": {}}
    seen_ids: set[str] = set()
    order = 0

    def add_node(
        *,
        item: Dict[str, Any],
        chapter_name: str,
        chapter_token: str,
        parent_id: Optional[str],
        path_tokens: List[str],
    ) -> Optional[str]:
        nonlocal order
        title_raw = item.get("title")
        title = _clean_title(title_raw if isinstance(title_raw, str) else "")
        if _is_noise_title(title):
            return None

        outline_type = str(item.get("type") or "").strip().lower()
        node_type = _node_type_from_outline_type(outline_type)
        explicit_tokens = _split_id_tokens(item.get("id"))
        order += 1
        node_id = _node_id(
            edition=edition,
            chapter_token=chapter_token,
            path_tokens=explicit_tokens or path_tokens,
            title=title,
            fallback_index=order,
        )
        while node_id in seen_ids:
            order += 1
            node_id = f"{node_id}.dup{order}"
        seen_ids.add(node_id)

        node = {
            "id": node_id,
            "name": title,
            "type": node_type,
            "stage": "大学",
            "grade_band": f"高等数学{edition}",
            "canonical": [title_raw] if isinstance(title_raw, str) and title_raw.strip() else [],
            "procedure": [],
            "prereq": [parent_id] if isinstance(parent_id, str) and parent_id else [],
            "short_name": title,
        }
        nodes.append(node)
        taxonomy[f"高等数学{edition}"].setdefault(chapter_name, [])
        taxonomy[f"高等数学{edition}"][chapter_name].append(node_id)
        return node_id

    for chapter_index, chapter in enumerate(items, start=1):
        if not isinstance(chapter, dict):
            continue
        chapter_title = _clean_title(chapter.get("title") if isinstance(chapter.get("title"), str) else "")
        if _is_noise_title(chapter_title):
            continue
        chapter_tokens = _split_id_tokens(chapter.get("id")) or [f"chap{chapter_index}"]
        chapter_token = chapter_tokens[0]
        chapter_node_id = add_node(
            item=chapter,
            chapter_name=chapter_title,
            chapter_token=chapter_token,
            parent_id=None,
            path_tokens=[f"chap{chapter_index}"],
        )
        children = chapter.get("children")
        if not isinstance(children, list):
            continue

        for section_index, section in enumerate(children, start=1):
            if not isinstance(section, dict):
                continue
            section_node_id = add_node(
                item=section,
                chapter_name=chapter_title,
                chapter_token=chapter_token,
                parent_id=chapter_node_id,
                path_tokens=[f"sec{section_index}"],
            )
            section_children = section.get("children")
            if not isinstance(section_children, list):
                continue
            for sub_index, sub in enumerate(section_children, start=1):
                if not isinstance(sub, dict):
                    continue
                add_node(
                    item=sub,
                    chapter_name=chapter_title,
                    chapter_token=chapter_token,
                    parent_id=section_node_id,
                    path_tokens=[f"sec{section_index}", f"sub{sub_index}"],
                )

    return nodes, taxonomy


def _build_schema(*, source_file: Path, outline_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    edition = _edition_from_filename(source_file)
    nodes, taxonomy = _iter_outline(outline_items, edition=edition)
    return {
        "meta": {
            "region": "中国（高等数学）",
            "standards": [
                f"高等数学{edition}教材目录知识点映射",
            ],
            "schema_version": "v1.0-gaoshu",
            "node_types": NODE_TYPES,
            "subject": "高等数学",
            "edition": edition,
            "source_outline_file": source_file.name,
        },
        "taxonomy_tree": taxonomy,
        "nodes": nodes,
    }


def _merge_keyword_schemas(schemas: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged_nodes: List[Dict[str, Any]] = []
    merged_taxonomy: Dict[str, Dict[str, List[str]]] = {}
    seen: set[str] = set()
    for schema in schemas:
        taxonomy = schema.get("taxonomy_tree")
        if isinstance(taxonomy, dict):
            for top_key, groups in taxonomy.items():
                if not isinstance(top_key, str) or not isinstance(groups, dict):
                    continue
                merged_groups = merged_taxonomy.setdefault(top_key, {})
                for group_name, ids in groups.items():
                    if not isinstance(group_name, str) or not isinstance(ids, list):
                        continue
                    bucket = merged_groups.setdefault(group_name, [])
                    for node_id in ids:
                        if isinstance(node_id, str) and node_id not in bucket:
                            bucket.append(node_id)
        nodes = schema.get("nodes")
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            if not isinstance(node_id, str) or not node_id or node_id in seen:
                continue
            seen.add(node_id)
            merged_nodes.append(node)
    return {
        "meta": {
            "region": "中国（高等数学）",
            "standards": ["高等数学教材目录知识点映射（A/B 合并）"],
            "schema_version": "v1.0-gaoshu",
            "node_types": NODE_TYPES,
            "subject": "高等数学",
            "edition": "A+B",
            "source_outline_file": "gaoshu/*.json",
        },
        "taxonomy_tree": merged_taxonomy,
        "nodes": merged_nodes,
    }


def convert_directory(root: Path) -> None:
    json_files = sorted(root.glob("*.json"))
    converted: List[Tuple[Path, Dict[str, Any]]] = []
    for file_path in json_files:
        name = file_path.name
        if name.endswith(".outline_raw.json"):
            continue
        if name == "key_word_gaoshu_merged.json":
            continue
        payload = _load_json(file_path)
        if _is_keyword_schema(payload):
            continue
        if not isinstance(payload, list):
            continue
        backup = file_path.with_name(f"{file_path.stem}.outline_raw.json")
        if not backup.exists():
            _write_json(backup, payload)
        schema = _build_schema(source_file=file_path, outline_items=payload)
        _write_json(file_path, schema)
        converted.append((file_path, schema))

    if converted:
        merged = _merge_keyword_schemas([item[1] for item in converted])
        merged_path = root / "key_word_gaoshu_merged.json"
        _write_json(merged_path, merged)
        print(f"converted {len(converted)} files. merged file: {merged_path}")
    else:
        print("no outline files converted")


if __name__ == "__main__":
    convert_directory(Path(__file__).resolve().parent)
