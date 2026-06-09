import sys
import os

sys.path.append(os.getcwd())

from exam_generator.pdf_export import render_markdown_to_pdf

def test_md_to_pdf(md_file_path, pdf_output_path):
    print(f"[*] Reading Markdown from: {md_file_path}")
    if not os.path.exists(md_file_path):
        print(f"[!] Error: File not found {md_file_path}")
        return

    with open(md_file_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    print(f"[*] Exporting to PDF: {pdf_output_path}...")
    try:
        render_markdown_to_pdf(md_content, pdf_output_path)
        print(f"[+] Success! PDF generated at {pdf_output_path}")
    except Exception as e:
        print(f"[!] Export failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    input_md = "output/final_exam_2024上海中考_20260507_154637.md"
    output_pdf = "output/test_debug_export.pdf"

    test_md_to_pdf(input_md, output_pdf)
