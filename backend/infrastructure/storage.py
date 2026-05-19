from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .security import safe_filename


@dataclass
class StoredFile:
    category: str
    file_name: str
    local_path: str
    content_type: str | None
    size_bytes: int


class LocalFileStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save_job_file(
        self,
        *,
        job_id: str,
        category: str,
        original_name: str,
        content: bytes,
        content_type: str | None,
        index: int,
    ) -> StoredFile:
        job_root = self.root / "jobs" / job_id / "inputs" / category
        job_root.mkdir(parents=True, exist_ok=True)
        file_name = safe_filename(original_name)
        final_name = f"{index:03d}_{file_name}"
        path = job_root / final_name
        path.write_bytes(content)
        return StoredFile(
            category=category,
            file_name=file_name,
            local_path=str(path),
            content_type=content_type,
            size_bytes=len(content),
        )

    def read_bytes(self, local_path: str) -> bytes:
        return Path(local_path).read_bytes()

