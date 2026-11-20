import json
import pandas as pd
import streamlit as st
from PIL import Image

from core.database import ReceiptDB
from core.ocr_engine import ReceiptOCREngine
from core.parser import ReceiptParser

st.set_page_config(
    page_title="Automated Receipt & Invoice Extractor",
    page_icon="🧾",
    layout="wide",
)


@st.cache_resource
def load_ocr_engine() -> ReceiptOCREngine:
    return ReceiptOCREngine()


ocr_engine = load_ocr_engine()
parser = ReceiptParser()
db = ReceiptDB()

# --- Sidebar Settings ---
with st.sidebar:
    st.header("Settings")
    use_ollama = st.toggle("Enable Local Ollama Fallback", value=False)
    ollama_model = st.text_input("Ollama Model", value="llama3", disabled=not use_ollama)
    st.caption("Uses 100% local PaddleOCR (ONNX) + Regex by default. Zero cloud API costs.")
    st.divider()
    if st.button("Clear Saved History", type="secondary", use_container_width=True):
        db.clear_all()
        st.rerun()

st.title("🧾 Automated Receipt & Invoice Extractor")
st.write("Upload receipt or invoice images to extract structured JSON and CSV data instantly.")

tab_extract, tab_history = st.tabs(["Extract Receipts", "Saved History"])

with tab_extract:
    uploaded_files = st.file_uploader(
        "Upload receipt images (JPG, PNG, WEBP)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        for idx, file in enumerate(uploaded_files):
            st.divider()
            col_img, col_data = st.columns([1, 1.3], gap="large")
            image = Image.open(file)

            with col_img:
                st.image(image, caption=file.name, use_container_width=True)

            with col_data:
                with st.spinner(f"Scanning {file.name}..."):
                    ocr_out = ocr_engine.extract_text(image)
                    parsed = parser.parse(
                        ocr_out["raw_text"],
                        ocr_out["lines"],
                        use_ollama=use_ollama,
                        ollama_model=ollama_model,
                    )

                st.subheader(f"Extracted Data — {file.name}")
                st.caption(
                    f"OCR Confidence: **{ocr_out['avg_confidence'] * 100:.1f}%** | "
                    f"Method: `{parsed['extraction_method']}`"
                )

                # Editable form so clients can verify/correct before saving or exporting
                with st.form(key=f"form_{idx}_{file.name}"):
                    c1, c2 = st.columns(2)
                    vendor = c1.text_input("Vendor / Store Name", value=parsed["vendor_name"] or "")
                    date_val = c2.text_input("Date (YYYY-MM-DD)", value=parsed["date"] or "")

                    c3, c4 = st.columns(2)
                    inv_no = c3.text_input("Invoice / Receipt #", value=parsed["invoice_number"] or "")
                    currency = c4.text_input("Currency", value=parsed["currency"] or "USD")

                    c5, c6 = st.columns(2)
                    tax_val = c5.number_input(
                        "Tax Amount", value=float(parsed["tax_amount"] or 0.0), format="%.2f"
                    )
                    total_val = c6.number_input(
                        "Total Amount", value=float(parsed["total_amount"] or 0.0), format="%.2f"
                    )

                    submitted = st.form_submit_button("Save to History", type="primary")

                final_record = {
                    "filename": file.name,
                    "vendor_name": vendor or None,
                    "date": date_val or None,
                    "invoice_number": inv_no or None,
                    "currency": currency,
                    "tax_amount": tax_val if tax_val > 0 else None,
                    "total_amount": total_val if total_val > 0 else None,
                    "confidence": ocr_out["avg_confidence"],
                }

                if submitted:
                    db.save_receipt(final_record)
                    st.success("Saved to history!")

                st.download_button(
                    label="Download JSON",
                    data=json.dumps(final_record, indent=2),
                    file_name=f"{file.name.rsplit('.', 1)[0]}.json",
                    mime="application/json",
                    key=f"dl_{idx}_{file.name}",
                )

                with st.expander("View Raw OCR Text"):
                    st.code(ocr_out["raw_text"] or "No text detected.", language="text")

with tab_history:
    records = db.fetch_all()
    if not records:
        st.info("No receipts saved yet. Upload and save a receipt to see it here.")
    else:
        df = pd.DataFrame(records)
        st.dataframe(df, use_container_width=True, hide_index=True)
        csv_data = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Export All History as CSV",
            data=csv_data,
            file_name="extracted_receipts.csv",
            mime="text/csv",
            type="primary",
        )