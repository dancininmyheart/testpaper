from __future__ import annotations

import argparse
import json
import re
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from mastery_engine import MasteryStore, utc_now


def _parse_range(value: str) -> timedelta:
    text = value.strip().lower()
    match = re.fullmatch(r"(\d+)\s*([dhm])", text)
    if not match:
        raise ValueError("range must match <number><d|h|m>, e.g. 30d")
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(minutes=amount)


def _level(mastery: float) -> str:
    if mastery >= 0.9:
        return "mastered"
    if mastery >= 0.75:
        return "high"
    if mastery >= 0.6:
        return "medium"
    if mastery >= 0.4:
        return "low"
    return "weak"


def _suggestions(weak_skills: List[Dict[str, Any]], err_dist: Dict[str, int]) -> List[str]:
    items: List[str] = []
    if err_dist.get("concept", 0) > 0:
        items.append("优先做概念回顾题与定义辨析题，先保证理解再提速。")
    if err_dist.get("calculation", 0) > 0:
        items.append("增加步骤化计算检查：每步写出中间结果并复核符号。")
    if err_dist.get("reading", 0) > 0:
        items.append("加强审题训练：圈画已知、未知和限制条件。")
    if weak_skills:
        top3 = ", ".join(s["skill_id"] for s in weak_skills[:3])
        items.append(f"本阶段优先修复薄弱知识点：{top3}。")
    if not items:
        items.append("继续保持当前练习节奏，优先做中等难度综合题。")
    return items


class MasteryApiService:
    def __init__(self, db_path: Path):
        self.store = MasteryStore(db_path)

    def close(self) -> None:
        self.store.close()

    def get_student_mastery(self, student_id: str, recent_limit: int) -> Dict[str, Any]:
        mastery = self.store.list_student_mastery(student_id)
        recent = self.store.list_recent_changes(student_id, limit=recent_limit)
        if not mastery and not recent:
            raise KeyError("student not found")
        vector = [
            {
                "skill_id": row["skill_id"],
                "mastery": round(float(row["mastery"]), 4),
                "level": _level(float(row["mastery"])),
                "last_update": row["last_update"],
                "uncertainty": row["uncertainty"],
            }
            for row in mastery
        ]
        return {
            "student_id": student_id,
            "skills": vector,
            "recent_change_reasons": recent,
        }

    def get_student_report(self, student_id: str, range_expr: str) -> Dict[str, Any]:
        window = _parse_range(range_expr)
        end = utc_now()
        start = end - window
        evidence = self.store.list_student_evidence_between(student_id, start.isoformat(), end.isoformat())
        mastery = self.store.list_student_mastery(student_id)
        if not mastery and not evidence:
            raise KeyError("student not found")

        err_dist: Dict[str, int] = {}
        by_skill: Dict[str, Dict[str, Any]] = {}
        for item in evidence:
            err = item["evidence"]["error_type"]
            err_dist[err] = err_dist.get(err, 0) + 1
            bucket = by_skill.setdefault(item["skill_id"], {"count": 0, "problems": []})
            bucket["count"] += 1
            bucket["problems"].append(item["problem_id"])

        weak_skills = [
            {
                "skill_id": row["skill_id"],
                "mastery": round(float(row["mastery"]), 4),
                "level": _level(float(row["mastery"])),
            }
            for row in mastery
            if float(row["mastery"]) < 0.6
        ]
        weak_skills.sort(key=lambda x: x["mastery"])

        weak_points: List[Dict[str, Any]] = []
        for skill in weak_skills[:10]:
            bucket = by_skill.get(skill["skill_id"], {"count": 0, "problems": []})
            weak_points.append(
                {
                    "skill_id": skill["skill_id"],
                    "mastery": skill["mastery"],
                    "problem_count": bucket["count"],
                    "problem_ids": sorted(set(bucket["problems"]))[:10],
                }
            )
        return {
            "student_id": student_id,
            "range_start": start.isoformat(),
            "range_end": end.isoformat(),
            "error_distribution": err_dist,
            "weak_points_top_n": weak_points,
            "suggestions": _suggestions(weak_skills, err_dist),
        }

    def get_exam_analysis(self, paper_id: str) -> Dict[str, Any]:
        rows = self.store.list_exam_analysis(paper_id)
        if not rows:
            raise KeyError("paper not found")
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            pid = row["problem_id"]
            node = grouped.setdefault(pid, {"problem_id": pid, "skills": []})
            node["skills"].append(
                {
                    "skill_id": row["skill_id"],
                    "source_type": row["source_type"],
                    "score_ratio": row["score_ratio"],
                    "count": row["n"],
                    "error_type": row["evidence"]["error_type"],
                }
            )
        return {"paper_id": paper_id, "problems": [grouped[k] for k in sorted(grouped)]}


def make_handler(service: MasteryApiService):
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, status: int, payload: Dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _query_value(self, params: Dict[str, List[str]], key: str, default: str) -> str:
            values = params.get(key, [])
            if not values:
                return default
            return values[0]

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            path = parsed.path
            try:
                if path == "/health":
                    self._respond(200, {"status": "ok"})
                    return
                if path.startswith("/student/") and path.endswith("/mastery"):
                    student_id = path[len("/student/") : -len("/mastery")]
                    limit_text = self._query_value(params, "recent_limit", "20")
                    recent_limit = max(1, min(100, int(limit_text)))
                    payload = service.get_student_mastery(student_id, recent_limit)
                    self._respond(200, payload)
                    return
                if path.startswith("/student/") and path.endswith("/report"):
                    student_id = path[len("/student/") : -len("/report")]
                    range_expr = self._query_value(params, "range", "30d")
                    payload = service.get_student_report(student_id, range_expr)
                    self._respond(200, payload)
                    return
                if path.startswith("/exam/") and path.endswith("/analysis"):
                    paper_id = path[len("/exam/") : -len("/analysis")]
                    payload = service.get_exam_analysis(paper_id)
                    self._respond(200, payload)
                    return
                self._respond(404, {"detail": "not found"})
            except ValueError as exc:
                self._respond(400, {"detail": str(exc)})
            except KeyError as exc:
                self._respond(404, {"detail": str(exc)})
            except Exception as exc:  # pragma: no cover
                self._respond(500, {"detail": f"internal error: {exc}"})

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def run_server(db_path: Path, host: str, port: int) -> None:
    service = MasteryApiService(db_path)
    handler = make_handler(service)
    server = ThreadingHTTPServer((host, port), handler)
    try:
        print(f"Mastery API running on http://{host}:{port}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.close()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run mastery API server.")
    parser.add_argument("--db", default="mastery.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run_server(Path(args.db), args.host, args.port)


if __name__ == "__main__":
    main()
