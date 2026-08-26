import io
import os
import re
from typing import Any, Dict, List

import fitz  # PyMuPDF
from PIL import Image
import pytesseract

from app.core.config import settings


class PDFProcessor:
    @staticmethod
    def is_meaningful_text(text: str) -> bool:
        if not text or not text.strip():
            return False
        clean_text = text.strip()
        if len(clean_text) < 20:
            return False
        words = re.findall(r"\b[a-zA-Z]{2,}\b", clean_text)
        if len(words) < 3:
            return False
        alpha_chars = sum(1 for c in clean_text if c.isalpha())
        if alpha_chars / float(len(clean_text)) < 0.20:
            return False
        return True

    @staticmethod
    def process_pdf(file_path: str, doc_dir: str) -> List[Dict[str, Any]]:
        pages_data = []

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found at path: {file_path}")

        try:
            with open(file_path, "rb") as f:
                pdf_bytes = f.read()
            pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as open_exc:
            raise ValueError(f"Corrupt or invalid PDF file: {open_exc}")


        try:
            for page_index in range(len(pdf_doc)):
                page_number = page_index + 1
                page = pdf_doc.load_page(page_index)

                # 1. Primary text extraction
                extracted_text = page.get_text("text") or ""
                usable_text = extracted_text.strip()

                ocr_applied = False
                ocr_failed = False
                ocr_error = None

                # 2. OCR Fallback if text extraction quality is insufficient
                if not PDFProcessor.is_meaningful_text(usable_text) and settings.OCR_ENABLED:
                    ocr_applied = True
                    best_ocr_text = ""

                    # Method A: Try OCR on embedded image objects
                    try:
                        embedded_imgs = page.get_images(full=True)
                        for img_info in embedded_imgs:
                            try:
                                xref = img_info[0]
                                base_image = pdf_doc.extract_image(xref)
                                pil_img = Image.open(io.BytesIO(base_image["image"]))
                                for psm_cfg in ["", "--psm 6"]:
                                    t = pytesseract.image_to_string(pil_img, lang=settings.OCR_LANGUAGE, config=psm_cfg)
                                    if t and len(t.strip()) > len(best_ocr_text):
                                        best_ocr_text = t.strip()
                            except Exception:
                                pass
                    except Exception as emb_exc:
                        print(f"OCR embedded image warning on page {page_number}: {emb_exc}")

                    # Method B: Try OCR on rendered pixmap
                    try:
                        pix = page.get_pixmap(dpi=200)
                        img_bytes = pix.tobytes("png")
                        pil_img = Image.open(io.BytesIO(img_bytes))
                        for psm_cfg in ["", "--psm 6"]:
                            t = pytesseract.image_to_string(pil_img, lang=settings.OCR_LANGUAGE, config=psm_cfg)
                            if t and len(t.strip()) > len(best_ocr_text):
                                best_ocr_text = t.strip()
                    except Exception as pix_exc:
                        print(f"OCR pixmap warning on page {page_number}: {pix_exc}")

                    if best_ocr_text:
                        usable_text = best_ocr_text
                    else:
                        ocr_failed = True
                        ocr_error = f"OCR failed to extract readable text on page {page_number}"

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
            if 'pdf_doc' in locals() and pdf_doc:
                try:
                    pdf_doc.close()
                except Exception:
                    pass
                del pdf_doc
            import gc
            gc.collect()

        return pages_data

