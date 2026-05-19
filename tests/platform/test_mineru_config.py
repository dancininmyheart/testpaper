from __future__ import annotations

import json
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from mineru_client import load_mineru_config


@contextmanager
def _workspace_temp_dir():
    root = Path.cwd() / "outputs" / "test_runtime"
    tmp_dir = root / f"mineru_config_{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _write_config(tmp_dir: Path, profile: dict) -> Path:
    config_path = tmp_dir / "llm_config.json"
    config_path.write_text(
        json.dumps(
            {
                "defaults": {"mineru_profile": "default"},
                "mineru": {"profiles": {"default": profile}},
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_load_mineru_config_accepts_direct_api_key() -> None:
    with _workspace_temp_dir() as tmp_dir:
        config_path = _write_config(tmp_dir, {"api_key": "direct-key"})

        config = load_mineru_config(config_path)

        assert config["api_key"] == "direct-key"
        assert config["profile_name"] == "default"


def test_load_mineru_config_prefers_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINERU_TEST_KEY", "env-key")
    with _workspace_temp_dir() as tmp_dir:
        config_path = _write_config(tmp_dir, {"api_key_env": "MINERU_TEST_KEY", "api_key": "direct-key"})

        config = load_mineru_config(config_path)

        assert config["api_key"] == "env-key"
        assert config["api_key_env"] == "MINERU_TEST_KEY"


def test_load_mineru_config_reports_missing_key_source() -> None:
    with _workspace_temp_dir() as tmp_dir:
        config_path = _write_config(tmp_dir, {"base_url": "https://mineru.net/api/v4"})

        with pytest.raises(RuntimeError, match="missing api_key_env or api_key"):
            load_mineru_config(config_path)


def test_real_mineru_default_profile_allows_long_polling() -> None:
    payload = json.loads(Path("llm_config.json").read_text(encoding="utf-8"))
    default_name = payload["defaults"]["mineru_profile"]
    profile = payload["mineru"]["profiles"][default_name]

    assert profile["timeout_sec"] >= 120
    assert profile["result_timeout_sec"] >= 900
    assert profile["poll_interval_sec"] == 5
