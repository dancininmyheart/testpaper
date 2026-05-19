import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
from ultralytics import YOLO


CLASS_MAP: Dict[int, str] = {
    0: "student_id",
    1: "subjective_problem",
    2: "fillin_problem",
    3: "objective_problem",
}

CLASS_COLORS: Dict[int, Tuple[int, int, int]] = {
    0: (120, 120, 120),
    1: (50, 130, 255),
    2: (50, 205, 50),
    3: (255, 120, 50),
}

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
DEFAULT_WEIGHTS = Path(__file__).resolve().parent / "weights" / "best.pt"


class BigQuestionSegmenter:
    def __init__(
        self,
        weights: Path = DEFAULT_WEIGHTS,
        imgsz: int = 640,
        conf: float = 0.1,
        iou: float = 0.7,
        device: Optional[str] = None,
        include_student_id: bool = False,
    ):
        self.weights = Path(weights).resolve()
        if not self.weights.exists():
            raise FileNotFoundError(f"Weight file not found: {self.weights}")

        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou
        self.device = device
        self.include_student_id = include_student_id
        self.model = YOLO(model=str(self.weights))

    @staticmethod
    def collect_images(input_path: Path, recursive: bool = False) -> List[Path]:
        input_path = Path(input_path).resolve()
        if input_path.is_file():
            if input_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                return [input_path]
            return []

        if not input_path.is_dir():
            return []

        iterator = input_path.rglob("*") if recursive else input_path.glob("*")
        images = [p for p in iterator if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS]
        return sorted(images)

    @staticmethod
    def safe_relative_path(image_path: Path, input_path: Path) -> Path:
        input_path = Path(input_path).resolve()
        image_path = Path(image_path).resolve()
        if input_path.is_dir():
            return image_path.relative_to(input_path)
        return Path(image_path.name)

    def segment_file(self, image_path: Path) -> Dict:
        payload, _ = self._segment_file_with_image(Path(image_path).resolve())
        return payload

    def run(
        self,
        input_path: Path,
        output_dir: Path,
        recursive: bool = False,
        save_crops: bool = True,
        save_visualized: bool = True,
    ) -> Dict:
        input_path = Path(input_path).resolve()
        output_dir = Path(output_dir).resolve()

        image_paths = self.collect_images(input_path=input_path, recursive=recursive)
        if not image_paths:
            raise FileNotFoundError(f"No image found under: {input_path}")

        json_root = output_dir / "json"
        crop_root = output_dir / "crops"
        vis_root = output_dir / "visualized"
        json_root.mkdir(parents=True, exist_ok=True)
        if save_crops:
            crop_root.mkdir(parents=True, exist_ok=True)
        if save_visualized:
            vis_root.mkdir(parents=True, exist_ok=True)

        manifest_items = []
        for image_path in image_paths:
            payload, image = self._segment_file_with_image(image_path=image_path)
            relative_path = self.safe_relative_path(image_path=image_path, input_path=input_path)
            payload["relative_path"] = str(relative_path)

            json_path = (json_root / relative_path).with_suffix(".json")
            json_path.parent.mkdir(parents=True, exist_ok=True)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            if save_crops:
                crop_dir = (crop_root / relative_path).with_suffix("")
                self._save_crops(image=image, detections=payload["detections"], crop_dir=crop_dir)

            if save_visualized:
                vis_path = vis_root / relative_path
                self._save_visualized(image=image, detections=payload["detections"], vis_path=vis_path)

            manifest_items.append(
                {
                    "relative_path": str(relative_path),
                    "json_path": str(json_path.relative_to(output_dir)),
                    "detection_count": payload["detection_count"],
                }
            )
            print(f"[OK] {relative_path} -> {payload['detection_count']} regions")

        manifest = {
            "input": str(input_path),
            "weights": str(self.weights),
            "imgsz": self.imgsz,
            "conf": self.conf,
            "iou": self.iou,
            "device": self.device,
            "total_images": len(image_paths),
            "items": manifest_items,
        }
        manifest_path = output_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        print(f"[DONE] output: {output_dir}")
        return manifest

    def _segment_file_with_image(self, image_path: Path) -> Tuple[Dict, Any]:
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"Failed to read image: {image_path}")

        result = self.model.predict(
            source=str(image_path),
            imgsz=self.imgsz,
            conf=self.conf,
            iou=self.iou,
            device=self.device,
            save=False,
            verbose=False,
        )[0]

        height, width = image.shape[:2]
        detections = []
        for box in result.boxes:
            cls_id = int(box.cls.item())
            if cls_id == 0 and not self.include_student_id:
                continue

            x1, y1, x2, y2 = box.xyxy[0].tolist()
            x1 = max(0, min(width - 1, int(round(x1))))
            y1 = max(0, min(height - 1, int(round(y1))))
            x2 = max(0, min(width, int(round(x2))))
            y2 = max(0, min(height, int(round(y2))))
            if x2 <= x1 or y2 <= y1:
                continue

            confidence = float(box.conf.item()) if box.conf is not None else 0.0
            detections.append(
                {
                    "class_id": cls_id,
                    "class_name": CLASS_MAP.get(cls_id, f"class_{cls_id}"),
                    "confidence": round(confidence, 6),
                    "bbox_xyxy": [x1, y1, x2, y2],
                    "bbox_xywh": [x1, y1, x2 - x1, y2 - y1],
                }
            )

        detections.sort(key=lambda d: (d["bbox_xyxy"][1], d["bbox_xyxy"][0]))
        for idx, detection in enumerate(detections, start=1):
            detection["index"] = idx

        payload = {
            "image_path": str(image_path),
            "image_size": {"width": width, "height": height},
            "detection_count": len(detections),
            "detections": detections,
        }
        return payload, image

    @staticmethod
    def _save_crops(image, detections: List[Dict], crop_dir: Path) -> None:
        crop_dir.mkdir(parents=True, exist_ok=True)
        for detection in detections:
            x1, y1, x2, y2 = detection["bbox_xyxy"]
            crop = image[y1:y2, x1:x2]
            crop_name = f"{detection['index']:02d}_{detection['class_name']}.jpg"
            cv2.imwrite(str(crop_dir / crop_name), crop)

    @staticmethod
    def _save_visualized(image, detections: List[Dict], vis_path: Path) -> None:
        vis_image = image.copy()
        for detection in detections:
            x1, y1, x2, y2 = detection["bbox_xyxy"]
            cls_id = detection["class_id"]
            color = CLASS_COLORS.get(cls_id, (255, 255, 255))
            label = f"{detection['index']} {detection['class_name']} {detection['confidence']:.2f}"
            cv2.rectangle(vis_image, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                vis_image,
                label,
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
                cv2.LINE_AA,
            )
        vis_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(vis_path), vis_image)
