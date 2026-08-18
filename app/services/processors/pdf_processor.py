import io
import os
from typing import Any, Dict, List

import fitz  # PyMuPDF
from PIL import Image
import pytesseract

from app.core.config import settings


class PDFProcessor:
    @staticmethod
    def process_pdf(file_path: str, doc_dir: str) -> List[Dict[str, Any]]:
        pages_data = []

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found at path: {file_path}")

        try:
            pdf_doc = fitz.open(file_path)
        except Exception as open_exc:
            raise ValueError(f"Corrupt or invalid PDF file: {open_exc}")

        try:
            for page_index in range(len(pdf_doc)):
                page_number = page_index + 1
                page = pdf_doc.load_page(page_index)

                # 1. Primary text extraction
                extracted_text = page.get_text("text") or ""
                ocr_applied = False
                ocr_failed = False
                ocr_error = None

                # 2. OCR Fallback if text is insufficient
                usable_text = extracted_text.strip()
                if len(usable_text) < 20 and settings.OCR_ENABLED:
                    ocr_applied = True
                    try:
                        pix = page.get_pixmap(dpi=150)
                        img_bytes = pix.tobytes("png")
                        pil_img = Image.open(io.BytesIO(img_bytes))
                        ocr_text = pytesseract.image_to_string(pil_img, lang=settings.OCR_LANGUAGE)
                        if ocr_text and ocr_text.strip():
                            usable_text = f"{usable_text}\n{ocr_text.strip()}".strip()
                    except Exception as ocr_exc:
                        ocr_failed = True
                        ocr_error = f"OCR failed on page {page_number}: {str(ocr_exc)}"
                        print(ocr_error)

                # 3. Image extraction
                page_images_dir = os.path.join(doc_dir, "pages", f"{page_number:04d}", "images")
                os.makedirs(page_images_dir, exist_ok=True)

                saved_image_paths = []
                image_list = page.get_images(full=True)

                for img_idx, img_info in enumerate(image_list):
                    try:
                        xref = img_info[0]
                        base_image = pdf_doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]

                        image_filename = f"image_{img_idx + 1}.{image_ext}"
                        full_img_path = os.path.join(page_images_dir, image_filename)

                        with open(full_img_path, "wb") as img_file:
                            img_file.write(image_bytes)

                        saved_image_paths.append(full_img_path)
                    except Exception as img_exc:
                        print(f"Image extraction warning on page {page_number}, img {img_idx}: {img_exc}")

                first_image_path = saved_image_paths[0] if saved_image_paths else None

                pages_data.append({
                    "page_number": page_number,
                    "content_type": "PAGE",
                    "text_content": usable_text,
                    "image_path": first_image_path,
                    "metadata_json": {
                        "image_count": len(saved_image_paths),
                        "extracted_image_paths": saved_image_paths,
                        "ocr_applied": ocr_applied,
                        "ocr_failed": ocr_failed,
                        "ocr_error": ocr_error,
                    },
                })
        finally:
            pdf_doc.close()

        return pages_data
