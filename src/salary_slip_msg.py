"""Salary Slip Message Sender — Upload Excel + salary slip files and send WhatsApp messages."""

import pandas as pd
import streamlit as st
import requests
from dotenv import load_dotenv
import os
from streamlit.runtime.uploaded_file_manager import UploadedFile
import base64
import logging
import datetime

# Configure logging
logger = logging.getLogger(__name__)

load_dotenv()

auth_key = os.getenv("AUTHKEY")
# Get WID from environment; fallback to None if not present (user said they'll add it later)
template_wid = os.getenv("SALARY_SLIP_WID")
REPO = os.getenv("REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

REQUIRED_COLUMNS = {"employee name", "emp id", "phone number"}
AUTHKEY_API_URL = "https://console.authkey.io/restapi/requestjson_v2.0.php"
BATCH_SIZE = 200


def get_previous_month_and_fy():
    """Calculate the name of the previous month and the current Financial Year."""
    today = datetime.date.today()
    # First day of the current month
    first = today.replace(day=1)
    # Go to previous month
    last_month = first - datetime.timedelta(days=1)
    prev_month_name = last_month.strftime("%B")  # e.g., "June"

    # Current Financial Year for today's date in India (starts in April)
    if today.month >= 4:
        start_year = today.year
    else:
        start_year = today.year - 1
    end_year_short = (start_year + 1) % 100
    current_fy = f"{start_year}-{end_year_short:02d}"  # e.g., "2026-27"

    return prev_month_name, current_fy


def extract_emp_id(filename: str, emp_ids: set[str]) -> str | None:
    """
    Find which emp_id is present as a substring in the filename.
    Sorted by length descending to match longer employee IDs first.
    """
    # Remove file extension and convert to uppercase
    name_without_ext = filename.rsplit(".", 1)[0].upper()
    
    emp_id = name_without_ext.split("_")[0]
    if emp_id in emp_ids:
        return emp_id
    return None


def get_files_url(salary_slip_files: list[UploadedFile], emp_ids: set[str]) -> dict[str, str]:
    emp_to_link = {}
    
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    
    for file in salary_slip_files:
        try:
            emp_id = extract_emp_id(file.name, emp_ids)
            if not emp_id:
                logger.warning(f"Could not extract employee ID from file name: {file.name}")
                continue  # Skip files that don't match any employee ID

            # Reset file pointer in case it was read before
            file.seek(0)
            
            # Upload file to github
            url = f"https://api.github.com/repos/{REPO}/contents/uploads/salary_slips/{emp_id}.pdf"
            content = base64.b64encode(file.read()).decode()
            
            # Check if file already exists (need sha to update)
            existing_resp = requests.get(url, headers=headers)
            sha = None
            if existing_resp.status_code == 200:
                sha = existing_resp.json().get("sha")
            
            data = {
                "message": f"Upload salary slip for {emp_id}",
                "content": content,
                "branch": "main"
            }
            
            # Include sha if file already exists (required for update)
            if sha:
                data["sha"] = sha

            resp = requests.put(url, json=data, headers=headers)
            resp_json = resp.json() if resp.text else {}

            if resp.status_code in [200, 201]:
                link = f"https://cdn.jsdelivr.net/gh/{REPO}@main/uploads/salary_slips/{emp_id}.pdf"
                emp_to_link[emp_id] = link
            else:
                logger.error(f"GitHub upload failed for {file.name}: status={resp.status_code}, response={resp_json}")

        except Exception as e:
            logger.exception(f"Exception uploading file {file.name}: {e}")
    
    return emp_to_link


def send_whatsapp_batch(messages: list[dict], wid: str) -> bool:
    """
    Send WhatsApp messages in batch using AuthKey API.
    messages: list of dicts with keys: mobile, pdf_link, employee_name, emp_id, month, fy
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
                "headerFileName": f"SalarySlip_{msg['emp_id']}.pdf",
            },
            "mobile": msg["mobile"],
            "bodyValues": {
                "1": msg["employee_name"],
                "2": msg["fy"],
                "3": msg["emp_id"],
                "4": msg["month"]
            }
        })

    payload = {
        "version": "2.0",
        "country_code": "91",
        "authkey": auth_key,
        "wid": wid,
        "type": "media",
        "data": data
    }

    try:
        resp = requests.post(AUTHKEY_API_URL, json=payload, headers=message_headers)
        if resp.status_code == 200 and resp.json().get("status") == "Success":
            return True
        
        logger.error(f"WhatsApp API failed: status={resp.status_code}, response={resp.text}, payload={payload}")
        return False
    except Exception as e:
        logger.exception(f"Exception sending WhatsApp batch: {e}, payload={payload}")
        return False


def process_and_send(mapping: dict, emp_to_link: dict, month: str, fy: str, wid: str) -> list[dict]:
    """
    Process employee data and send WhatsApp messages.
    Returns a list of result dicts for display.
    """
    results = []
    messages = []

    for emp_id, info in mapping.items():
        pdf_link = emp_to_link.get(emp_id)
        if not pdf_link:
            logger.error(f"No PDF link for employee {emp_id}, mapping: {emp_to_link}")
            results.append({
                "Employee ID": emp_id,
                "Employee Name": info["name"],
                "Phone Number": info["phone"],
                "Status": "Failed",
                "Reason": "Salary slip file could not be uploaded. Please re-upload the file."
            })
            continue

        # Add message
        messages.append({
            "mobile": info["phone"],
            "pdf_link": pdf_link,
            "employee_name": info["name"],
            "emp_id": emp_id,
            "month": month,
            "fy": fy
        })

        results.append({
            "Employee ID": emp_id,
            "Employee Name": info["name"],
            "Phone Number": info["phone"],
            "Status": "Queued",
            "Reason": ""
        })

    # Send in batches
    failed_emp_ids = set()
    if messages:
        progress_bar = st.progress(0, text="Sending messages...")
        total_batches = (len(messages) + BATCH_SIZE - 1) // BATCH_SIZE
        
        for i in range(0, len(messages), BATCH_SIZE):
            batch = messages[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            progress_bar.progress(batch_num / total_batches, text="Sending messages...")
            success = send_whatsapp_batch(batch, wid)
            if not success:
                # Track which employee IDs were in this failed batch
                for msg in batch:
                    failed_emp_ids.add(msg["emp_id"])

        progress_bar.empty()

    # Update results based on batch outcomes
    for r in results:
        if r["Status"] == "Queued":
            if r["Employee ID"] in failed_emp_ids:
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


def validate_data(df: pd.DataFrame, emp_ids_from_files: list[str]) -> dict[str, dict] | None:
    """
    Validate Excel data and uploaded filenames.
    Returns a mapping {emp_id: {phone, name}} or None on failure.
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

    # Check for duplicate employee IDs in Excel
    duplicates = df[df["emp id"].duplicated(keep=False)]["emp id"].unique()
    if len(duplicates) > 0:
        st.error(f"Duplicate Employee IDs in Excel: {', '.join(duplicates)}")
        return None

    # Build sets (ensure string comparison)
    excel_emp_ids = set(df["emp id"])
    file_emp_ids = set(str(eid) for eid in emp_ids_from_files)

    missing = excel_emp_ids - file_emp_ids
    if missing:
        st.warning(f"Employee IDs in Excel but not in files: {missing}")
        st.info("Upload the missing salary slip files and try again.")
        return None

    # Build mapping
    mapping = {
        row["emp id"]: {
            "phone": row["phone number"],
            "name": row["employee name"]
        }
        for _, row in df.iterrows()
    }
    return mapping


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
def main():
    st.header("Send Salary Slip")
    st.write(
        "Upload an **Excel file** with columns: `employee name`, `emp id`, and `phone number`.\n\n"
        "Upload **salary slip files** (multi-select). Filename should contain employee ID (e.g., `EMP001` or `EMP001_salary_slip.pdf` etc.)"
    )

    # Date defaults calculation
    prev_month_default, fy_default = get_previous_month_and_fy()

    st.subheader("Message Parameters")
    col1, col2 = st.columns(2)
    with col1:
        month_val = st.text_input("Month (3)", value=prev_month_default)
    with col2:
        fy_val = st.text_input("Financial Year (4)", value=fy_default)

    excel_file = st.file_uploader("Excel file", type=["xlsx", "xls"])
    salary_slip_files = st.file_uploader("Salary Slip files", accept_multiple_files=True)

    if st.button("Send Messages"):
        if not template_wid:
            st.error("Environment variable `SALARY_SLIP_WID` is not configured. Please add it to your environment and restart.")
            return

        if not excel_file:
            st.error("Please upload the Excel file first.")
            return
        if not salary_slip_files:
            st.error("Please upload at least one salary slip file.")
            return

        df = load_excel(excel_file)
        if df is None:
            return

        # Build list of emp ids from Excel to help match files
        excel_emp_ids = set(df["emp id"].astype(str).str.strip()) if "emp id" in df.columns else set()

        # Extract emp ids from filenames for validation
        file_emp_ids = [extract_emp_id(f.name, excel_emp_ids) for f in salary_slip_files]
        file_emp_ids = [eid for eid in file_emp_ids if eid]  # Remove None values

        if not file_emp_ids:
            st.error("Could not match employee IDs from uploaded filenames. Expected filenames to contain employee IDs matching the Excel sheet.")
            return

        # Validate data BEFORE uploading files
        mapping = validate_data(df, file_emp_ids)
        if mapping is None:
            return

        # Upload files only after validation passes
        with st.spinner("Uploading salary slip files..."):
            emp_to_link = get_files_url(salary_slip_files, excel_emp_ids)

        results = process_and_send(mapping, emp_to_link, month_val, fy_val, template_wid)

        # Separate successful and failed
        failed = [r for r in results if r["Status"] == "Failed"]
        success_count = len(results) - len(failed)

        if success_count > 0:
            st.success(f"✅ Successfully sent messages for {success_count} employee(s).")

        if failed:
            st.error(f"❌ Failed to send messages for {len(failed)} employee(s). Please review and retry.")
            failed_df = pd.DataFrame(failed)
            failed_df = failed_df[["Employee ID", "Employee Name", "Phone Number", "Reason"]]
            st.dataframe(failed_df, width='stretch', hide_index=True)


if __name__ == "__main__":
    main()
