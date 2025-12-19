import pandas as pd
import streamlit as st
import requests
from dotenv import load_dotenv
import os

load_dotenv()

access_token = os.getenv("ACCESS_TOKEN")
phone_number_id = os.getenv("PHONE_NUMBER_ID")

REQUIRED_COLUMNS = {"phone number", 'dealer name', 'dealer code'}


def send_whatsapp_msg(phone: str, dealer_name: str, dealer_code: str) -> bool:
    """Send welcome WhatsApp message using the welcome_new_user template."""
    
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
            "name": "welcome_existing_user",
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "parameter_name": "dealer_name",
                            "text": dealer_name
                        },
                        {
                            "type": "text",
                            "parameter_name": "dealer_code",
                            "text": dealer_code
                        }
                    ]
                }
            ]
        }
    }
    
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
    phone_numbers = df["phone number"].tolist()
    dealer_names = df["dealer name"].tolist()
    dealer_codes = df["dealer code"].tolist()
    return phone_numbers, dealer_names, dealer_codes


def process_and_send(phone_numbers: list[str], dealer_names: list[str], dealer_codes: list[str]) -> list[dict]:
    """Send welcome messages for each phone number, return results list."""
    results = []
    
    for phone, dealer_name, dealer_code in zip(phone_numbers, dealer_names, dealer_codes):
        try:
            ok = send_whatsapp_msg(phone, dealer_name, dealer_code)
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
        
        phone_numbers, dealer_names, dealer_codes = data

        st.info(f"Found {len(phone_numbers)} phone number(s) to process.")

        with st.spinner("Sending welcome messages..."):
            results = process_and_send(phone_numbers, dealer_names, dealer_codes)

        st.success(f"Processed {len(results)} phone number(s).")
        st.dataframe(pd.DataFrame(results))


if __name__ == "__main__":
    main()
