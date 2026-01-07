import pandas as pd
import streamlit as st
import requests
from dotenv import load_dotenv
import os

load_dotenv()

auth_key = os.getenv("AUTHKEY")
template_id = os.getenv("EXISTING_USER_WID")

REQUIRED_COLUMNS = {"phone number", 'dealer name', 'dealer code'}


def send_whatsapp_msg(data: list[dict]) -> bool:
    """Send welcome WhatsApp message using the welcome_new_user template."""
    
    message_url = f"https://console.authkey.io/restapi/requestjson_v2.0.php"
    message_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_key}"
    }

    payload = {
        "version": "2.0",
        "country_code": "91",
        "wid": template_id,
        "type": "text",
        "data":
        [
            {
                "mobile": item["phone_number"], 
                "bodyValues": {
                    "1": item["dealer_name"],
                    "2": item["dealer_code"]
                }
            } for item in data
        ]
    }

    resp = requests.post(message_url, headers=message_headers, json=payload)

    if resp.status_code != 200:
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
        st.error(f"Excel must have column: phone number, dealer name, dealer code")
        return None

    # Trim whitespace
    df["phone number"] = df["phone number"].astype(str).str.strip()
    df["dealer name"] = df["dealer name"].astype(str).str.strip()
    df["dealer code"] = df["dealer code"].astype(str).str.strip()

    # Check for empty cells
    empty_mask = df["phone number"].eq("") | df["dealer name"].eq("") | df["dealer code"].eq("")
    if empty_mask.any():
        st.warning(f"Rows with missing phone numbers: {list(df.index[empty_mask])}")
        st.info("Fill all phone numbers and re-upload.")
        return None

    # Return unique phone numbers, dealer names and codes
    return df.to_dict()

# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
def main():
    st.header("Welcome New User Message Sender")
    st.markdown(
        "Upload an **Excel file** with column: `phone number`, `dealer name`, `dealer code`.\n\n"
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

        data = validate_data(df)
        if data is None:
            return

        st.info(f"Found {len(data)} phone number(s) to process.")

        with st.spinner("Sending welcome messages..."):
            result = send_whatsapp_msg(data)

        if result:
            st.success(f"Processed {len(data)} phone number(s).")
        else:
            st.error(f"Unable to send messages. Please check if the numbers entered are correct!")

if __name__ == "__main__":
    main()
