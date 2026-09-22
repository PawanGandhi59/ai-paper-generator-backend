import io
import logging
import os
import re
from typing import Any, Dict, List

import fitz  # PyMuPDF
from PIL import Image
import pytesseract

from app.core.config import settings

logger = logging.getLogger(__name__)


class PDFProcessor:
    @staticmethod
    def is_meaningful_text(text: str) -> bool:
        if not text or not text.strip():
            return False
        clean_text = text.strip()
        if len(clean_text) < 20:
            return False
        words = re.findall(r"\b[^\W\d_]{2,}\b", clean_text)
        if len(words) < 3:
            return False
        alpha_chars = sum(1 for c in clean_text if c.isalpha())
        if alpha_chars / float(len(clean_text)) < 0.15:
            return False
        return True

    @staticmethod
    def process_pdf(file_path: str, doc_dir: str, ocr_mode: str = "fast") -> List[Dict[str, Any]]:
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
                extracted_text = (page.get_text("text") or "").replace("\x00", "")
                usable_text = extracted_text.strip()

                ocr_applied = False
                ocr_failed = False
                ocr_error = None

                # 2. OCR Fallback if text extraction quality is insufficient
                if not PDFProcessor.is_meaningful_text(usable_text) and settings.OCR_ENABLED:
                    ocr_applied = True
                    best_ocr_text = ""

                    if ocr_mode == "thorough":
                        # High-fidelity multi-pass OCR for reference papers and scans:
                        # Method A: Try OCR on embedded raw image objects directly at native resolution
                        try:
                            embedded_imgs = page.get_images(full=True)
                            for img_info in embedded_imgs:
                                try:
                                    xref = img_info[0]
                                    base_image = pdf_doc.extract_image(xref)
                                    pil_img = Image.open(io.BytesIO(base_image["image"]))
                                    for psm_cfg in ["", "--psm 6"]:
                                        t = pytesseract.image_to_string(pil_img, lang=settings.OCR_LANGUAGE, config=psm_cfg).replace("\x00", "")
                                        if t and len(t.strip()) > len(best_ocr_text):
                                            best_ocr_text = t.strip()
                                except Exception:
                                    pass
                        except Exception as emb_exc:
                            logger.warning(f"OCR embedded image warning on page {page_number}: {emb_exc}")

                        # Method B: Try OCR on rendered pixmap at high resolution (200 DPI)
                        try:
                            pix = page.get_pixmap(dpi=200)
                            img_bytes = pix.tobytes("png")
                            pil_img = Image.open(io.BytesIO(img_bytes))
                            for psm_cfg in ["", "--psm 6"]:
                                t = pytesseract.image_to_string(pil_img, lang=settings.OCR_LANGUAGE, config=psm_cfg).replace("\x00", "")
                                if t and len(t.strip()) > len(best_ocr_text):
                                    best_ocr_text = t.strip()
                        except Exception as pix_exc:
                            logger.warning(f"OCR pixmap warning on page {page_number}: {pix_exc}")
                    else:
                        # Fast single-pass OCR for books and long textbooks (150 DPI with automatic page segmentation)
                        try:
                            pix = page.get_pixmap(dpi=150)
                            pil_img = Image.open(io.BytesIO(pix.tobytes("png")))
                            ocr_text = pytesseract.image_to_string(
                                pil_img,
                                lang=settings.OCR_LANGUAGE,
                                config="--psm 3",
                            ).replace("\x00", "").strip()
                            if ocr_text:
                                best_ocr_text = ocr_text
                        except Exception as pix_exc:
                            logger.warning(f"OCR pixmap warning on page {page_number}: {pix_exc}")

                    if best_ocr_text:
                        usable_text = best_ocr_text.replace("\x00", "").strip()
                    else:
                        ocr_failed = True
                        ocr_error = f"OCR failed to extract readable text on page {page_number}"

                pages_data.append({
                    "page_number": page_number,
                    "content_type": "PAGE",
                    "text_content": usable_text,
                    "image_path": None,
                    "metadata_json": {
                        "image_count": 0,
                        "extracted_image_paths": [],
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

