from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG_PATH = Path(r"D:\project\testpaper\llm_config.json")
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "mineru_kie_output"


def _import_kie_client():
    try:
        from mineru_kie_sdk import MineruKIEClient  # type: ignore

        return MineruKIEClient
    except ImportError:
        try:
            from mineru import MineruKIEClient  # type: ignore

            return MineruKIEClient
        except ImportError as exc:
            raise SystemExit(
                "未安装 MinerU KIE SDK。请先执行 `pip install mineru-kie-sdk`，"
                "或按文档在本地源码目录执行 `pip install -e .`。"
            ) from exc


def _ensure_file_exists(file_path: Path) -> Path:
    resolved = file_path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise SystemExit(f"文件不存在: {resolved}")
    return resolved


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_kie_config(config_path: Path) -> Dict[str, Any]:
    resolved = _ensure_file_exists(config_path)
    payload = _read_json(resolved)

    mineru = payload.get("mineru")
    if not isinstance(mineru, dict):
        raise SystemExit(f"配置文件缺少 mineru 节点: {resolved}")

    kie = mineru.get("kie")
    if not isinstance(kie, dict):
        raise SystemExit(f"配置文件缺少 mineru.kie 节点: {resolved}")

    base_url = kie.get("base_url")
    pipeline_id = kie.get("pipeline_id")
    if not isinstance(base_url, str) or not base_url.strip():
        raise SystemExit("mineru.kie.base_url 未配置")
    if not isinstance(pipeline_id, str) or not pipeline_id.strip():
        raise SystemExit("mineru.kie.pipeline_id 未配置")

    timeout_sec = kie.get("timeout_sec", 30)
    result_timeout_sec = kie.get("result_timeout_sec", 60)
    poll_interval_sec = kie.get("poll_interval_sec", 5)
    use_env_proxy = bool(kie.get("use_env_proxy", False))

    return {
        "base_url": base_url.strip(),
        "pipeline_id": pipeline_id.strip(),
        "timeout_sec": int(timeout_sec),
        "result_timeout_sec": int(result_timeout_sec),
        "poll_interval_sec": int(poll_interval_sec),
        "use_env_proxy": use_env_proxy,
    }


def _normalize_result_step(step: Any) -> Any:
    if step is None:
        return None
    if hasattr(step, "get_result") and callable(step.get_result):
        return step.get_result()
    return step


def save_results(output_dir: Path, stem: str, result_bundle: Dict[str, Any]) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_path = output_dir / f"{stem}.kie.result.json"
    parse_path = output_dir / f"{stem}.parse.json"
    split_path = output_dir / f"{stem}.split.json"
    extract_path = output_dir / f"{stem}.extract.json"

    summary_path.write_text(json.dumps(result_bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    parse_path.write_text(json.dumps(result_bundle.get("parse"), ensure_ascii=False, indent=2), encoding="utf-8")
    split_path.write_text(json.dumps(result_bundle.get("split"), ensure_ascii=False, indent=2), encoding="utf-8")
    extract_path.write_text(json.dumps(result_bundle.get("extract"), ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "summary": str(summary_path),
        "parse": str(parse_path),
        "split": str(split_path),
        "extract": str(extract_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MinerU KIE SDK 调用工具：上传单文件并轮询 parse/split/extract 结果。")
    parser.add_argument("--file", required=True, help="待上传文件路径，支持 pdf/jpg/jpeg/png")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help=f"配置文件路径，默认 {DEFAULT_CONFIG_PATH}")
    parser.add_argument("--pipeline-id", default=None, help="覆盖配置中的 pipeline_id")
    parser.add_argument("--base-url", default=None, help="覆盖配置中的 KIE base_url")
    parser.add_argument("--request-timeout", type=int, default=None, help="覆盖配置中的 timeout_sec")
    parser.add_argument("--result-timeout", type=int, default=None, help="结果轮询超时秒数，-1 表示一直等待")
    parser.add_argument("--poll-interval", type=int, default=None, help="轮询间隔秒数")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="结果输出目录")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    file_path = _ensure_file_exists(Path(args.file))
    config = load_kie_config(Path(args.config))

    base_url = args.base_url or config["base_url"]
    pipeline_id = args.pipeline_id or config["pipeline_id"]
    request_timeout = args.request_timeout if args.request_timeout is not None else config["timeout_sec"]
    result_timeout = args.result_timeout if args.result_timeout is not None else config["result_timeout_sec"]
    poll_interval = args.poll_interval if args.poll_interval is not None else config["poll_interval_sec"]

    if pipeline_id == "YOUR_KIE_PIPELINE_ID":
        raise SystemExit("请先在 llm_config.json 中将 mineru.kie.pipeline_id 替换为真实的 Pipeline ID。")

    MineruKIEClient = _import_kie_client()
    client = MineruKIEClient(
        base_url=base_url,
        pipeline_id=pipeline_id,
        timeout=request_timeout,
    )

    if hasattr(client, "session") and hasattr(client.session, "trust_env"):
        client.session.trust_env = config["use_env_proxy"]

    try:
        file_ids = client.upload_file(file_path)
        print(f"上传成功，file_ids={file_ids}")
    except ValueError as exc:
        raise SystemExit(f"文件参数错误: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"上传失败: {exc}") from exc

    try:
        results = client.get_result(file_ids=file_ids, timeout=result_timeout, poll_interval=poll_interval)
    except TimeoutError as exc:
        raise SystemExit(f"轮询超时: {exc}") from exc
    except ValueError as exc:
        raise SystemExit(f"获取结果参数错误: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"获取结果失败: {exc}") from exc

    result_bundle = {
        "file_ids": file_ids,
        "parse": _normalize_result_step(results.get("parse")),
        "split": _normalize_result_step(results.get("split")),
        "extract": _normalize_result_step(results.get("extract")),
    }

    saved = save_results(Path(args.output_dir).resolve(), file_path.stem, result_bundle)
    print(json.dumps({"file_ids": file_ids, "saved": saved}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
