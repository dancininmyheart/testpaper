import argparse
import sys
import os
import json

# Add current directory to path so we can import exam_generator
sys.path.append(os.getcwd())

from exam_generator.config_loader import load_config
from exam_generator.pipeline import ExamGenerationPipeline

def main():
    parser = argparse.ArgumentParser(description="试卷智能重组系统 — 命令行入口")
    
    parser.add_argument("--input", "-i", type=str, required=True, help="结构化题目 JSON 文件路径")
    parser.add_argument("--config", "-c", type=str, default="exam_generator/config.yaml", help="配置文件路径")
    parser.add_argument("--workers", "-w", type=int, default=4, help="并发线程数")

    args = parser.parse_args()

    print("\n" + "="*60)
    print("      🚀 试卷智能重组系统 (Agentic Exam Generator) 🚀")
    print("="*60)

    if not os.path.exists(args.input):
        print(f"\n[!] 错误: 找不到输入文件 {args.input}")
        sys.exit(1)

    if not args.input.endswith(".json"):
        print("\n[!] 错误: 命令行目前仅支持结构化题目 JSON 文件。")
        print("格式示例：{\"questions\": [{\"id\": \"Q1\", \"type\": \"单选题\", \"stem\": \"x+y=1\", \"score\": 5}]}")
        sys.exit(1)

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        questions = data.get("questions", [])
        if not questions:
            print("\n[!] 错误: 输入 JSON 文件中没有包含 questions 列表")
            sys.exit(1)
            
        config = load_config(args.config)
        pipeline = ExamGenerationPipeline(config=config, max_workers=args.workers)
        pipeline.run(questions=questions)
    except Exception as e:
        print(f"\n[!] 运行过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
