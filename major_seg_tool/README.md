# Major Segmentation Tool

Standalone answer-sheet major-question segmentation tool based on YOLO.

## 1. What to copy

Copy this directory to your target project:

```text
major_seg_tool/
  __init__.py
  big_question_segmenter.py
  cli.py
  requirements.txt
  weights/
```

Then place your model file at:

```text
major_seg_tool/weights/best.pt
```

Or pass `--weights` with an external path.

## 2. Install dependencies

```bash
pip install -r major_seg_tool/requirements.txt
```

## 3. CLI usage

```bash
# from repository root
python major_seg_tool/cli.py -i ./input_images -o ./outputs/major_seg --recursive
```

Common params:

- `--weights`: YOLO weight path
- `--imgsz`: inference size, default `640`
- `--conf`: confidence threshold, default `0.25`
- `--iou`: NMS IoU threshold, default `0.7`
- `--device`: `cpu`, `0`, `0,1` ...
- `--include-student-id`: include class `student_id`
- `--no-crops`: skip crop output
- `--no-vis`: skip visualization output

## 4. Output layout

```text
outputs/major_seg/
  manifest.json
  json/
  crops/
  visualized/
```

## 5. Python API usage

```python
from pathlib import Path
from major_seg_tool import BigQuestionSegmenter

segmenter = BigQuestionSegmenter(
    weights=Path("major_seg_tool/weights/best.pt"),
    imgsz=640,
    conf=0.25,
    iou=0.7,
    device="cpu",
)

# Single image -> dict
result = segmenter.segment_file(Path("test.jpg"))
print(result["detection_count"])

# Batch run -> save json/crops/visualized
segmenter.run(
    input_path=Path("input_images"),
    output_dir=Path("outputs/major_seg"),
    recursive=True,
    save_crops=True,
    save_visualized=True,
)
```
