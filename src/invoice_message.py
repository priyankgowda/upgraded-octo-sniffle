"""Invoice Message Sender — Upload Excel + invoice files and send WhatsApp messages."""

import pandas as pd
import streamlit as st
import requests
from dotenv import load_dotenv
import os
from streamlit.runtime.uploaded_file_manager import UploadedFile
import base64
import logging

# Configure logging
logger = logging.getLogger(__name__)

load_dotenv()

auth_key = os.getenv("AUTHKEY")
template_wid = os.getenv("INVOICE_MSG_WID")
REPO = os.getenv("REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

REQUIRED_COLUMNS = {"invoice number", "phone number", "dealer name", "amount", "no of cases"}
AUTHKEY_API_URL = "https://console.authkey.io/restapi/requestjson_v2.0.php"
BATCH_SIZE = 200


def extract_invoice_number(filename: str) -> str | None:
    """Return the part of the filename before the first underscore."""
    filename= filename.split(".")[0]
    if not filename:
        logger.error(f"Failed to extract invoice number - empty filename after removing extension: {filename}")
        return None
    token = filename.split("_")[0]
    return token.strip() or None


def format_inr(number):
    number = float(number)
    whole, decimal = f"{number:.2f}".split(".")
    
    # Last 3 digits stay together
    last_three = whole[-3:]
    remaining = whole[:-3]

    if remaining:
        # Add commas after every 2 digits in the remaining part
        remaining = ",".join([remaining[max(i-2, 0):i] for i in range(len(remaining), 0, -2)][::-1])
        formatted = remaining + "," + last_three
    else:
        formatted = last_three

    return formatted + "." + decimal


def get_files_url(invoice_files: list[UploadedFile]) -> dict[str, str]:
    inv_to_link = {}
    
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    
    for file in invoice_files:
        try:
            inv_no = extract_invoice_number(file.name)
            if not inv_no:
                continue  # Skip files with invalid names

            # Reset file pointer in case it was read before
            file.seek(0)
            
            # Upload file to github
            url = f"https://api.github.com/repos/{REPO}/contents/uploads/{inv_no}.pdf"
            content = base64.b64encode(file.read()).decode()
            
            # Check if file already exists (need sha to update)
            existing_resp = requests.get(url, headers=headers)
            sha = None
            if existing_resp.status_code == 200:
                sha = existing_resp.json().get("sha")
            
            data = {
                "message": f"Upload {inv_no}",
                "content": content,
                "branch": "main"
            }
            
            # Include sha if file already exists (required for update)
            if sha:
                data["sha"] = sha

            resp = requests.put(url, json=data, headers=headers)
            resp_json = resp.json() if resp.text else {}

            if resp.status_code in [200, 201]:
                link = f"https://cdn.jsdelivr.net/gh/{REPO}@main/uploads/{inv_no}.pdf"
                inv_to_link[inv_no] = link
            else:
                logger.error(f"GitHub upload failed for {file.name}: status={resp.status_code}, response={resp_json}")

        except Exception as e:
            logger.exception(f"Exception uploading file {file.name}: {e}")
    
    return inv_to_link


def send_whatsapp_batch(messages: list[dict]) -> bool:
    """
    Send WhatsApp messages in batch using AuthKey API.
    messages: list of dicts with keys: mobile, pdf_link, dealer_name, no_of_cases, amount
    """
    if not messages:
        return True

    message_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_key}"
    }

    data = []
    for msg in messages:
        data.append({
            "headerValues": {
                "headerData": msg["pdf_link"],
                "headerFileName": f"{msg['invoice_no']}/2025-26.pdf",
            },
            "mobile": msg["mobile"],
            "bodyValues": {
                "1": msg["dealer_name"],
                "2": str(msg["no_of_cases"]),
                "3": format_inr(msg["amount"])
            }
        })

    payload = {
        "version": "2.0",
        "country_code": "91",
        "authkey": auth_key,
        "wid": template_wid,
        "type": "media",
        "data": data
    }

    try:
        resp = requests.post(AUTHKEY_API_URL, json=payload,headers=message_headers)
        if resp.status_code == 200 and resp.json().get("status") == "Success":
            return True
        
        logger.error(f"WhatsApp API failed: status={resp.status_code}, response={resp.text}, payload={payload}")
        return False
    except Exception as e:
        logger.exception(f"Exception sending WhatsApp batch: {e}, payload={payload}")
        return False


def process_and_send(mapping: dict, inv_to_link: dict) -> list[dict]:
    """
    Process invoice data and send WhatsApp messages to both phone and sales numbers.
    Returns a list of result dicts for display.
    """
    results = []
    messages = []

    for invoice_no, info in mapping.items():
        pdf_link = inv_to_link.get(invoice_no)
        if not pdf_link:
            logger.error(f"No PDF link for invoice {invoice_no}, mapping: {inv_to_link}")
            results.append({
                "Invoice Number": invoice_no,
                "Dealer Name": info["dealer"],
                "Phone Number": info["phone"],
                "Sales Number": info["sales_number"],
                "Status": "Failed",
                "Reason": "Invoice file could not be uploaded. Please re-upload the file."
            })
            continue

        # Add message for phone number
        messages.append({
            "mobile": info["phone"],
            "pdf_link": pdf_link,
            "dealer_name": info["dealer"],
            "no_of_cases": info["no_of_cases"],
            "amount": info["amount"],
            "invoice_no": invoice_no
        })

        # Add message for sales number only if provided
        if info["sales_number"]:
            messages.append({
                "mobile": info["sales_number"],
                "pdf_link": pdf_link,
                "dealer_name": info["dealer"],
                "no_of_cases": info["no_of_cases"],
                "amount": info["amount"],
                "invoice_no": invoice_no
            })

        results.append({
            "Invoice Number": invoice_no,
            "Dealer Name": info["dealer"],
            "Phone Number": info["phone"],
            "Sales Number": info["sales_number"],
            "Status": "Queued",
            "Reason": ""
        })

    # Send in batches (hidden from user)
    failed_invoice_nos = set()
    if messages:
        progress_bar = st.progress(0, text="Sending messages...")
        total_batches = (len(messages) + BATCH_SIZE - 1) // BATCH_SIZE
        
        for i in range(0, len(messages), BATCH_SIZE):
            batch = messages[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            progress_bar.progress(batch_num / total_batches, text="Sending messages...")
            success = send_whatsapp_batch(batch)
            if not success:
                # Track which invoice numbers were in this failed batch
                for msg in batch:
                    failed_invoice_nos.add(msg["invoice_no"])

        progress_bar.empty()

    # Update results based on batch outcomes
    for r in results:
        if r["Status"] == "Queued":
            if r["Invoice Number"] in failed_invoice_nos:
                r["Status"] = "Failed"
                r["Reason"] = "Message could not be delivered. Please try again later."
            else:
                r["Status"] = "Sent"
                r["Reason"] = ""

    return results


def load_excel(file) -> pd.DataFrame | None:
    """Read Excel and normalize column names to lowercase."""
    try:
        df = pd.read_excel(file)
    except Exception as e:
        logger.exception(f"Failed to read Excel file {file.name}: {e}")
        st.error(f"Failed to read Excel: {e}")
        return None
    df.columns = df.columns.str.strip().str.lower()
    return df


def validate_data(df: pd.DataFrame, invoice_numbers: list[str]) -> dict[str, dict] | None:
    """
    Validate Excel data and uploaded filenames.
    Returns a mapping {invoice_number: {phone, dealer, amount, no_of_cases, sales_number}} or None on failure.
    """
    if df.empty:
        logger.error("Validation failed: Excel file is empty")
        st.error("Excel file is empty.")
        return None

    # Check required columns
    if not REQUIRED_COLUMNS.issubset(df.columns):
        missing_cols = REQUIRED_COLUMNS - set(df.columns)
        logger.error(f"Validation failed: Missing columns {missing_cols}, found: {list(df.columns)}")
        st.error(f"Excel is missing columns: {', '.join(missing_cols)}")
        return None

    # Trim whitespace and convert to string
    for col in REQUIRED_COLUMNS:
        df[col] = df[col].astype(str).str.strip()

    # Check for empty cells in required columns (also catch 'nan' from NaN values)
    empty_mask = df[list(REQUIRED_COLUMNS)].apply(
        lambda col: col.eq("") | col.str.lower().eq("nan")
    ).any(axis=1)
    if empty_mask.any():
        bad_rows = [i + 2 for i in df.index[empty_mask]]  # +2 for 1-based index + header row
        st.warning(f"Rows with missing values (Excel row numbers): {bad_rows}")
        st.info("Fill all required fields and re-upload.")
        return None

    # Handle optional sales number column
    if "sales number" in df.columns:
        df["sales number"] = df["sales number"].astype(str).str.strip()
        # Treat 'nan' as empty
        df["sales number"] = df["sales number"].apply(lambda x: "" if x.lower() == "nan" else x)
    else:
        df["sales number"] = ""

    # Check for duplicate invoice numbers in Excel
    duplicates = df[df["invoice number"].duplicated(keep=False)]["invoice number"].unique()
    if len(duplicates) > 0:
        st.error(f"Duplicate invoice numbers in Excel: {', '.join(duplicates)}")
        return None

    # Build sets (ensure string comparison)
    excel_invoices = set(df["invoice number"])
    file_invoices = set(str(inv) for inv in invoice_numbers)


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
            "amount": row["amount"],
            "no_of_cases": row["no of cases"],
            "sales_number": row["sales number"]
        }
        for _, row in df.iterrows()
    }
    return mapping


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
def main():
    st.header("Invoice Message Sender")
    st.write(
        "Upload an **Excel file** with columns: `dealer name`, `invoice number`, `phone number`, `amount`, `no of cases`, and optionally `sales number`.\n\n"
        "Upload **invoice files** (multi-select). Filename format: `<invoice_number>_<anything>.<ext>`"
    )

    excel_file = st.file_uploader("Excel file", type=["xlsx", "xls"])
    invoice_files = st.file_uploader("Invoice files", accept_multiple_files=True)

    if st.button("Send Messages"):
        if not excel_file:
            st.error("Please upload the Excel file first.")
            return
        if not invoice_files:
            st.error("Please upload at least one invoice file.")
            return

        df = load_excel(excel_file)
        if df is None:
            return

        # Extract invoice numbers from filenames for validation
        file_invoice_numbers = [extract_invoice_number(f.name) for f in invoice_files]
        file_invoice_numbers = [inv for inv in file_invoice_numbers if inv]  # Remove None values

        if not file_invoice_numbers:
            st.error("Could not extract invoice numbers from uploaded filenames. Expected format: `<invoice_number>_<anything>.<ext>` or `<invoice_number>.<ext>`")
            return

        # Validate data BEFORE uploading files
        mapping = validate_data(df, file_invoice_numbers)
        if mapping is None:
            return

        # Upload files only after validation passes
        with st.spinner("Uploading invoice files..."):
            inv_to_link = get_files_url(invoice_files)

        results = process_and_send(mapping, inv_to_link)

        # Separate successful and failed
        failed = [r for r in results if r["Status"] == "Failed"]
        success_count = len(results) - len(failed)

        if success_count > 0:
            st.success(f"✅ Successfully sent messages for {success_count} invoice(s).")

        if failed:
            st.error(f"❌ Failed to send messages for {len(failed)} invoice(s). Please review and retry.")
            failed_df = pd.DataFrame(failed)
            # Remove Status column, keep only relevant info
            failed_df = failed_df[["Invoice Number", "Dealer Name", "Phone Number", "Sales Number", "Reason"]]
            st.dataframe(failed_df, width='stretch', hide_index=True)


if __name__ == "__main__":
    main()
