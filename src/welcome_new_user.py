"""Welcome New User — Upload Excel with phone numbers and send welcome WhatsApp messages."""

import pandas as pd
import streamlit as st
import requests
from dotenv import load_dotenv
import os

load_dotenv()

access_token = os.getenv("ACCESS_TOKEN")

REQUIRED_COLUMNS = {"phone number"}


def send_whatsapp_msg(phone: str) -> bool:
    """Send welcome WhatsApp message using the welcome_new_user template."""
    
    phone_number_id = "905890485940579"
    
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
            "name": "welcome_new_user",
            "language": {"code": "en"}
        }
    }
    
    st.info(f"Sending welcome WhatsApp message to {phone}...")
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


def validate_data(df: pd.DataFrame) -> list[str] | None:
    """
    Validate Excel data.
    Returns a list of phone numbers or None on failure.
    """
    # Check required columns
    if not REQUIRED_COLUMNS.issubset(df.columns):
        st.error(f"Excel must have column: phone number")
        return None

    # Trim whitespace
    df["phone number"] = df["phone number"].astype(str).str.strip()

    # Check for empty cells
    empty_mask = df["phone number"].eq("")
    if empty_mask.any():
        st.warning(f"Rows with missing phone numbers: {list(df.index[empty_mask])}")
        st.info("Fill all phone numbers and re-upload.")
        return None

    # Return unique phone numbers
    phone_numbers = df["phone number"].unique().tolist()
    return phone_numbers


def process_and_send(phone_numbers: list[str]) -> list[dict]:
    """Send welcome messages for each phone number, return results list."""
    results = []
    
    for phone in phone_numbers:
        try:
            ok = send_whatsapp_msg(phone)
            status = "sent" if ok else "failed"
        except Exception as e:
            status = f"error: {e}"

        results.append({"phone": phone, "status": status})
    
    return results


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
def main():
    st.header("Welcome New User Message Sender")
    st.write(
        "Upload an **Excel file** with column: `phone number`.\n\n"
        "The system will send a welcome message to all new users."
    )

    excel_file = st.file_uploader("Excel file with phone numbers", type=["xlsx", "xls"])

    if st.button("Send Welcome Messages"):
        if not excel_file:
            st.error("Upload the Excel file first.")
            return

        df = load_excel(excel_file)
        if df is None:
            return

        phone_numbers = validate_data(df)
        if phone_numbers is None:
            return

        st.info(f"Found {len(phone_numbers)} phone number(s) to process.")

        with st.spinner("Sending welcome messages..."):
            results = process_and_send(phone_numbers)

        st.success(f"Processed {len(results)} phone number(s).")
        st.dataframe(pd.DataFrame(results))


if __name__ == "__main__":
    main()
