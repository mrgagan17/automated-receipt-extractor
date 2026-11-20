import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
import requests


class ReceiptParser:
    DATE_PATTERNS = [
        r"\b(\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2})\b",                  # YYYY-MM-DD
        r"\b(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})\b",                # DD/MM/YYYY or MM/DD/YYYY
        r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+\d{2,4})\b",
        r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}[\s,]+\d{2,4})\b",
    ]

    TOTAL_KEYWORDS = [
        r"grand\s*total",
        r"net\s*payable",
        r"amount\s*due",
        r"total\s*amount",
        r"balance\s*due",
        r"total\s*payable",
        r"\btotal\b",
    ]

    TAX_KEYWORDS = [r"\bgst\b", r"\bcgst\b", r"\bsgst\b", r"\bvat\b", r"\btax\b"]

    INVOICE_PATTERN = re.compile(
        r"(?:invoice|inv|bill|receipt)\s*(?:no\.?|#|number)?\s*[:\-]?\s*([A-Z0-9\-\/]{3,20})",
        re.IGNORECASE,
    )

    CURRENCY_MAP = {
        "₹": "INR",
        "rs.": "INR",
        "rs": "INR",
        "inr": "INR",
        "$": "USD",
        "usd": "USD",
        "€": "EUR",
        "eur": "EUR",
        "£": "GBP",
        "gbp": "GBP",
    }

    def _detect_currency(self, text: str) -> str:
        # 1. Check explicit currency symbols first
        symbol_map = {"$": "USD", "₹": "INR", "€": "EUR", "£": "GBP"}
        for symbol, code in symbol_map.items():
            if symbol in text:
                return code

        # 2. Fall back to whole-word currency codes only
        word_patterns = [
            (r"\b(?:inr|rs\.?)\b", "INR"),
            (r"\busd\b", "USD"),
            (r"\beur\b", "EUR"),
            (r"\bgbp\b", "GBP"),
        ]
        for pattern, code in word_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return code

        return "USD"

    def _extract_vendor(self, lines: List[Dict[str, Any]]) -> Optional[str]:
        """Usually the first non-numeric, non-generic line at the top of the receipt."""
        ignore_words = {"tax invoice", "receipt", "cash memo", "bill", "welcome", "original"}
        for line in lines[:5]:
            text = line["text"].strip()
            if len(text) >= 3 and not re.fullmatch(r"[\d\W]+", text):
                if text.lower() not in ignore_words:
                    return text
        return None

    def _extract_date(self, text: str) -> Optional[str]:
        for pattern in self.DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw_date = match.group(1)
                return self._normalize_date(raw_date)
        return None

    def _normalize_date(self, raw_date: str) -> str:
        formats = [
            "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y",
            "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%m/%d/%y",
            "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
            "%b %d %Y", "%B %d %Y",
        ]
        cleaned = re.sub(r"\s+", " ", raw_date.strip())
        for fmt in formats:
            try:
                return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return raw_date

    def _extract_amount_by_keywords(self, text: str, keywords: List[str]) -> Optional[float]:
        lines = text.splitlines()
        amount_regex = r"(?:[$₹€£]|rs\.?|inr|usd)?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+\.\d{2})"

        for kw in keywords:
            for i, line in enumerate(lines):
                if re.search(kw, line, re.IGNORECASE):
                    # Check same line first, then the immediately following line
                    search_window = line + (" " + lines[i + 1] if i + 1 < len(lines) else "")
                    matches = re.findall(amount_regex, search_window, re.IGNORECASE)
                    if matches:
                        val_str = matches[-1].replace(",", "")
                        return float(val_str)
        return None

    def _extract_fallback_max_amount(self, text: str) -> Optional[float]:
        matches = re.findall(r"\b(\d{1,3}(?:,\d{3})*\.\d{2})\b", text)
        if not matches:
            return None
        values = [float(m.replace(",", "")) for m in matches]
        return max(values) if values else None

    def parse(
        self,
        raw_text: str,
        lines: List[Dict[str, Any]],
        use_ollama: bool = False,
        ollama_model: str = "llama3",
        ollama_url: str = "http://localhost:11434/api/generate",
    ) -> Dict[str, Any]:
        vendor = self._extract_vendor(lines)
        date = self._extract_date(raw_text)
        currency = self._detect_currency(raw_text)
        total = self._extract_amount_by_keywords(raw_text, self.TOTAL_KEYWORDS)
        if total is None:
            total = self._extract_fallback_max_amount(raw_text)

        tax = self._extract_amount_by_keywords(raw_text, self.TAX_KEYWORDS)
        inv_match = self.INVOICE_PATTERN.search(raw_text)
        invoice_number = inv_match.group(1) if inv_match else None

        result = {
            "vendor_name": vendor,
            "date": date,
            "invoice_number": invoice_number,
            "currency": currency,
            "tax_amount": tax,
            "total_amount": total,
            "extraction_method": "regex",
        }

        if use_ollama:
            llm_result = self._refine_with_ollama(raw_text, ollama_model, ollama_url)
            if llm_result:
                # Merge LLM output only where it provides non-null values
                for key in ["vendor_name", "date", "invoice_number", "currency", "tax_amount", "total_amount"]:
                    if llm_result.get(key) is not None:
                        result[key] = llm_result[key]
                result["extraction_method"] = f"regex+ollama({ollama_model})"

        return result

    def _refine_with_ollama(
        self, raw_text: str, model: str, url: str
    ) -> Optional[Dict[str, Any]]:
        prompt = (
            "Extract receipt details from the OCR text below. "
            "Return ONLY a valid JSON object with keys: "
            "vendor_name (string|null), date (YYYY-MM-DD|null), invoice_number (string|null), "
            "currency (3-letter code), tax_amount (number|null), total_amount (number|null).\n\n"
            f"OCR TEXT:\n{raw_text}"
        )
        try:
            resp = requests.post(
                url,
                json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=15,
            )
            resp.raise_for_status()
            return json.loads(resp.json().get("response", "{}"))
        except Exception:
            return None