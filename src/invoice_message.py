"""Invoice Message Sender — Upload Excel + invoice files and send WhatsApp messages."""

import pandas as pd
import streamlit as st
import requests
from dotenv import load_dotenv
import os

load_dotenv()

access_token = os.getenv("ACCESS_TOKEN")

REQUIRED_COLUMNS = {"invoice number", "phone number", "dealer name", "amount"}


def extract_invoice_number(filename: str) -> str | None:
    """Return the part of the filename before the first underscore."""
    if not filename:
        return None
    token = filename.split("_")[0]
    return token.strip() or None


#real function to send whatsapp message with pdf attachment
def send_whatsapp_msg(
    phone: str,
    customer_name: str,
    invoice_no: str,
    amount: str,
    pdf_bytes: bytes
) -> bool:
    
    phone_number_id = "905890485940579"
    
    # Step 1: Upload the PDF to WhatsApp to get a media ID
    upload_url = f"https://graph.facebook.com/v22.0/{phone_number_id}/media"
    upload_headers = {
        "Authorization": f"Bearer {access_token}"
    }

    upload_data = {
        "messaging_product": "whatsapp",
        "type": "document"
    }

    upload_files = {
        "file": (f"{invoice_no}.pdf", pdf_bytes, "application/pdf")
    }
    
    st.info(f"Uploading PDF for invoice {invoice_no}...")
    upload_resp = requests.post(upload_url, headers=upload_headers, data=upload_data, files=upload_files)
    
    if upload_resp.status_code != 200:
        st.error(f"Failed to upload PDF: {upload_resp.text}")
        return False
    
    media_id = upload_resp.json().get("id")
    if not media_id:
        st.error(f"No media ID returned: {upload_resp.text}")
        return False
    
    # Step 2: Send the WhatsApp message with the media ID
    message_url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
    message_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": f"91{phone}",
        "type": "template",
        "template": {
            "name": "invoice_message",
            "language": {"code": "en_IN"},
            "components": [
                {
                    "type": "header",
                    "parameters": [
                        {
                            "type": "document",
                            "document": {
                                "id": media_id,
                                "filename": f"{invoice_no}.pdf"
                            }
                        }
                    ]
                },
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "parameter_name": "customer_name",
                            "text": customer_name
                        },
                        {
                            "type": "text",
                            "parameter_name": "invoice_number",
                            "text": invoice_no
                        },
                        {
                            "type": "text",
                            "parameter_name": "amount",
                            "text": str(amount)
                        }
                    ]
                }
            ]
        }
    }
    
    st.info(f"Sending WhatsApp message to {phone} for invoice {invoice_no}...")
    resp = requests.post(message_url, headers=message_headers, json=payload)

    if resp.status_code != 200:
        st.error(f"WhatsApp API error for {phone}: {resp.text}")
        return False

    return True


def load_excel(file) -> pd.DataFrame | None:
    """Read Excel and normalize column names to lowercase."""
    try:
        df = pd.read_excel(file)
    except Exception as e:
        st.error(f"Failed to read Excel: {e}")
        return None
    df.columns = df.columns.str.strip().str.lower()
    return df


def validate_data(df: pd.DataFrame, filenames: list[str]) -> dict[str, dict] | None:
    """
    Validate Excel data and uploaded filenames.
    Returns a mapping {invoice_number: {phone, dealer}} or None on failure.
    """
    # Check required columns
    if not REQUIRED_COLUMNS.issubset(df.columns):
        st.error(f"Excel must have columns: {', '.join(REQUIRED_COLUMNS)}")
        return None

    # Trim whitespace
    for col in REQUIRED_COLUMNS:
        df[col] = df[col].astype(str).str.strip()

    # Check for empty cells
    empty_mask = df[list(REQUIRED_COLUMNS)].eq("").any(axis=1)
    if empty_mask.any():
        st.warning(f"Rows with missing values: {list(df.index[empty_mask])}")
        st.info("Fill all required fields and re-upload.")
        return None

    # Build sets
    excel_invoices = set(df["invoice number"])
    file_invoices = {extract_invoice_number(f) for f in filenames} - {None}

    missing = excel_invoices - file_invoices
    if missing:
        st.warning(f"Invoice numbers in Excel but not in files: {missing}")
        st.info("Upload the missing invoice files and try again.")
        return None

    # Build mapping
    mapping = {
        row["invoice number"]: {
            "phone": row["phone number"],
            "dealer": row["dealer name"],
            "amount": row["amount"]
        }
        for _, row in df.iterrows()
    }
    return mapping


def process_and_send(mapping: dict[str, dict], invoice_files: list) -> list[dict]:
    """Send messages for each uploaded invoice file, return results list."""
    results = []
    
    for file_obj in invoice_files:
        fname = file_obj.name
        inv = extract_invoice_number(fname)
        if not inv or inv not in mapping:
            results.append({"file": fname, "invoice": inv, "status": "skipped"})
            continue

        info = mapping[inv]
        phone = info["phone"]
        dealer = info["dealer"]
        amount = info["amount"]

        # Send WhatsApp message with PDF bytes directly
        try:
            pdf_bytes = file_obj.read()
            ok = send_whatsapp_msg(phone, dealer, inv, str(amount), pdf_bytes)
            status = "sent" if ok else "failed"
        except Exception as e:
            status = f"error: {e}"

        results.append({"file": fname, "invoice": inv, "phone": phone, "dealer": dealer, "status": status})
    return results


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
def main():
    st.header("Invoice Message Sender")
    st.write(
        "Upload an **Excel file** with columns: `dealer name`, `invoice number`, `phone number`, `amount`.\n\n"
        "Upload **invoice files** (multi-select). Filename format: `<invoice_number>_<anything>.<ext>`"
    )

    excel_file = st.file_uploader("Excel file", type=["xlsx", "xls"])
    invoice_files = st.file_uploader("Invoice files", accept_multiple_files=True)

    if st.button("Send Messages"):
        if not excel_file:
            st.error("Upload the Excel file first.")
            return
        if not invoice_files:
            st.error("Upload at least one invoice file.")
            return

        df = load_excel(excel_file)
        if df is None:
            return

        filenames = [f.name for f in invoice_files]
        mapping = validate_data(df, filenames)
        if mapping is None:
            return

        with st.spinner("Sending..."):
            results = process_and_send(mapping, invoice_files)

        st.success(f"Processed {len(results)} file(s).")
        st.dataframe(pd.DataFrame(results))


if __name__ == "__main__":
    main()
