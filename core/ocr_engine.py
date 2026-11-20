from typing import Dict, Any, List
import cv2
import numpy as np
from PIL import Image, ImageOps
from rapidocr_onnxruntime import RapidOCR


class ReceiptOCREngine:
    def __init__(self) -> None:
        self.engine = RapidOCR()

    def preprocess_image(self, pil_image: Image.Image) -> np.ndarray:
        """Auto-orient, convert to RGB, and enhance contrast for better OCR."""
        pil_image = ImageOps.exif_transpose(pil_image).convert("RGB")
        img = np.array(pil_image)

        # Upscale small receipt images for clearer text recognition
        h, w = img.shape[:2]
        if w < 1000:
            scale = 1000 / w
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        # Convert to LAB color space and apply CLAHE to the lightness channel
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l_channel)
        enhanced = cv2.merge((cl, a_channel, b_channel))
        return cv2.cvtColor(enhanced, cv2.COLOR_LAB2RGB)

    def extract_text(self, pil_image: Image.Image) -> Dict[str, Any]:
        """Run OCR and return structured lines, raw text, and average confidence."""
        processed_img = self.preprocess_image(pil_image)
        result, _ = self.engine(processed_img)

        if not result:
            return {"raw_text": "", "lines": [], "avg_confidence": 0.0}

        lines: List[Dict[str, Any]] = []
        confidences: List[float] = []

        for item in result:
            _, text, conf = item
            cleaned = text.strip()
            if cleaned:
                lines.append({"text": cleaned, "confidence": round(float(conf), 3)})
                confidences.append(float(conf))

        raw_text = "\n".join(line["text"] for line in lines)
        avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

        return {
            "raw_text": raw_text,
            "lines": lines,
            "avg_confidence": avg_conf,
        }