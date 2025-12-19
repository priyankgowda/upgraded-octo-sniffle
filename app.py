import streamlit as st
from pathlib import Path

dir_path = Path(__file__).parent

st.set_page_config(
    page_title="Message Dashboard",
    page_icon=":material/account_balance_wallet:",
    layout="wide",
)

page = st.navigation(
    {
        "Pages": [
            st.Page(
                page= dir_path / "src" / "invoice_message.py",
                title="Invoice message",
                icon=":material/receipt_long:",
            ),
            st.Page(
                page= dir_path / "src" / "welcome_new_user.py",
                title="New User",
                icon=":material/person_add:",
            ),
            st.Page(
                page= dir_path / "src" / "msg_existing_user.py",
                title="Welcome Existing User",
                icon=":material/person:",
            )
        ]
    },
    expanded=True
)
page.run()
