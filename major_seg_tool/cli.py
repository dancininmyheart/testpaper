import argparse
from pathlib import Path

try:
    from .big_question_segmenter import BigQuestionSegmenter, DEFAULT_WEIGHTS
except ImportError:
    from big_question_segmenter import BigQuestionSegmenter, DEFAULT_WEIGHTS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Answer-sheet major-question segmentation tool.")
    parser.add_argument("-i", "--input", required=True, help="Image file or directory path.")
    parser.add_argument("-o", "--output", default="outputs/major_segmentation", help="Output directory.")
    parser.add_argument(
        "--weights",
        default=str(DEFAULT_WEIGHTS),
        help="YOLO weight file path. Default is ./weights/best.pt",
    )
    parser.add_argument("--imgsz", type=int, default=640, help="Inference image size.")
    parser.add_argument("--conf", type=float, default=0.1, help="Confidence threshold.")
    parser.add_argument("--iou", type=float, default=0.7, help="NMS IoU threshold.")
    parser.add_argument("--device", default=None, help="Inference device, e.g. cpu, 0, 0,1.")
    parser.add_argument("--recursive", action="store_true", help="Recursively scan input directory.")
    parser.add_argument(
        "--include-student-id",
        action="store_true",
        help="Include student_id class (class 0) in outputs.",
    )
    parser.add_argument("--no-crops", action="store_true", help="Do not save crop images.")
    parser.add_argument("--no-vis", action="store_true", help="Do not save visualization images.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    segmenter = BigQuestionSegmenter(
        weights=Path(args.weights),
        imgsz=args.imgsz,
        conf=args.conf,
        iou=args.iou,
        device=args.device,
        include_student_id=args.include_student_id,
    )
    segmenter.run(
        input_path=Path(args.input),
        output_dir=Path(args.output),
        recursive=args.recursive,
        save_crops=not args.no_crops,
        save_visualized=not args.no_vis,
    )


if __name__ == "__main__":
    main()
