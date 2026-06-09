import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

class KnowledgeManager:
    def __init__(self, file_path: str | Path | None = None):
        if file_path is None:
            file_path = Path(__file__).resolve().parent / "knowledge.json"
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Knowledge file not found: {file_path}")
        
        with file_path.open("r", encoding="utf-8") as f:
            self.data = json.load(f)
        
        # Build flattened lookups
        self.topics_map = {}
        self._build_maps()

    def _build_maps(self):
        for domain in self.data.get("domains", []):
            for subdomain in domain.get("subdomains", []):
                for topic in subdomain.get("topics", []):
                    self.topics_map[topic["id"]] = {
                        "name": topic["name"],
                        "grade": topic.get("grade"),
                        "key_points": topic.get("key_points", []),
                        "parent_subdomain": subdomain["name"],
                        "parent_domain": domain["name"]
                    }

    def get_topics_summary(self) -> List[Dict[str, str]]:
        """Return a list of all topic IDs and names for the first stage of analysis."""
        return [{"id": tid, "name": info["name"]} for tid, info in self.topics_map.items()]

    def get_topic_details(self, topic_id: str) -> Optional[Dict[str, Any]]:
        """Return full details for a specific topic."""
        return self.topics_map.get(topic_id)

    def get_core_competencies(self) -> List[str]:
        """Return the list of core competencies."""
        return self.data.get("core_competencies", {}).get("items", [])

    def get_math_ideas(self) -> List[str]:
        """Return the list of key mathematical ideas."""
        return self.data.get("key_math_ideas", [])

    def get_standard_info(self) -> Dict[str, str]:
        """Return metadata about the curriculum standard."""
        return self.data.get("metadata", {})
