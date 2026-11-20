import sqlite3
from datetime import datetime
from typing import Any, Dict, List


class ReceiptDB:
    def __init__(self, db_path: str = "receipts.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS receipts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT,
                    vendor_name TEXT,
                    receipt_date TEXT,
                    invoice_number TEXT,
                    currency TEXT,
                    tax_amount REAL,
                    total_amount REAL,
                    confidence REAL,
                    created_at TEXT
                )
                """
            )

    def save_receipt(self, data: Dict[str, Any]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO receipts (
                    filename, vendor_name, receipt_date, invoice_number,
                    currency, tax_amount, total_amount, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("filename"),
                    data.get("vendor_name"),
                    data.get("date"),
                    data.get("invoice_number"),
                    data.get("currency"),
                    data.get("tax_amount"),
                    data.get("total_amount"),
                    data.get("confidence"),
                    datetime.utcnow().isoformat(timespec="seconds"),
                ),
            )

    def fetch_all(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM receipts ORDER BY id DESC").fetchall()
            return [dict(r) for r in rows]

    def clear_all(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM receipts")