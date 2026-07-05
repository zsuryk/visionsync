import streamlit as st
import sqlite3
import uuid
import json
import base64
import re
import requests
import pandas as pd

# ── Page Configuration ──
st.set_page_config(page_title="VisionSync | Document Ledger", layout="wide")

# ── Constants ──
DB_PATH = "db.sqlite"
API_URL = "https://model.service-inference.ai/v1/chat/completions"
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a financial document extraction AI. Extract the following fields from the document image and return ONLY valid JSON. No markdown, no code fences.
{
  "vendor_name": "string (Supports English and Traditional Chinese)",
  "transaction_date": "string (Strict ISO-8601 Format: YYYY-MM-DD)",
  "gross_amount": "float (Normalized numeric value, no currency symbols)",
  "currency": "string (Standard 3-letter currency code, e.g., HKD, USD)",
  "ledger_category": "string (Standard operating bucket)"
}"""

# ── Database Layer ──

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ledger_entries (
            id TEXT PRIMARY KEY,
            file_path TEXT,
            vendor_name TEXT,
            transaction_date TEXT,
            gross_amount REAL,
            currency TEXT,
            ledger_category TEXT,
            is_verified INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def load_entries():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM ledger_entries ORDER BY rowid DESC", conn)
    conn.close()
    if not df.empty:
        df["is_verified"] = df["is_verified"].astype(bool)
    return df

def insert_entry(file_path, vendor_name, transaction_date, gross_amount, currency, ledger_category):
    entry_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO ledger_entries (id, file_path, vendor_name, transaction_date, gross_amount, currency, ledger_category) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (entry_id, file_path, vendor_name, transaction_date, gross_amount, currency, ledger_category)
    )
    conn.commit()
    conn.close()
    return entry_id

def update_entries(df):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for _, row in df.iterrows():
        cursor.execute(
            """UPDATE ledger_entries SET
                vendor_name = ?,
                transaction_date = ?,
                gross_amount = ?,
                currency = ?,
                ledger_category = ?,
                is_verified = ?
            WHERE id = ?""",
            (
                row["vendor_name"],
                row["transaction_date"],
                float(row["gross_amount"]),
                row["currency"],
                row["ledger_category"],
                int(row["is_verified"]),
                row["id"]
            )
        )
    conn.commit()
    conn.close()

# ── API Layer ──

def encode_image(file_bytes):
    return base64.b64encode(file_bytes).decode("utf-8")

def call_llm(b64_image):
    api_key = st.secrets.get("INFERENCE_AI_API_KEY")
    if not api_key:
        st.error("API key not configured. Add INFERENCE_AI_API_KEY to .streamlit/secrets.toml")
        return None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract financial data from this document image."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_image}"
                        }
                    }
                ]
            }
        ],
        "response_format": {"type": "json_object"}
    }
    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE)
        return json.loads(content)
    except json.JSONDecodeError:
        st.error("LLM returned malformed JSON. Check raw response below.")
        with st.expander("Raw LLM Response"):
            st.code(content)
        return None
    except requests.RequestException as e:
        st.error(f"API request failed: {e}")
        return None

# ── Bootstrap Database ──

if "db_inited" not in st.session_state:
    init_db()
    st.session_state["db_inited"] = True

# ── UI Header ──

st.title("VisionSync")
st.caption("Source-Linked Document-to-Books Pipeline — Vision Co Challenge")
st.divider()

# ── File Upload & Processing ──

uploaded_file = st.file_uploader("Upload a financial document", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    file_key = f"{uploaded_file.name}_{uploaded_file.size}"
    processed_key = st.session_state.get("processed_key")

    if processed_key != file_key:
        st.session_state["processed_key"] = file_key
        b64_image = encode_image(uploaded_file.getvalue())
        with st.spinner("Extracting ledger data via Multimodal LLM..."):
            result = call_llm(b64_image)
        if result:
            entry_id = insert_entry(
                file_path=b64_image,
                vendor_name=result.get("vendor_name", ""),
                transaction_date=result.get("transaction_date", ""),
                gross_amount=result.get("gross_amount", 0.0),
                currency=result.get("currency", ""),
                ledger_category=result.get("ledger_category", "")
            )
            st.session_state["last_entry_id"] = entry_id
            st.success("Entry extracted and saved to ledger!")
            st.rerun()

st.divider()

# ── Main Split-Screen Layout ──

df = load_entries()
col1, col2 = st.columns([1, 1.5])

# ── LEFT COLUMN: Source Asset Vault ──

with col1:
    st.subheader("Source Asset Vault")
    if not df.empty:
        entry_options = {
            row["id"]: f"{row['vendor_name']} — {row['transaction_date']}"
            for _, row in df.iterrows()
        }
        selector_key = "entry_selector"
        if "last_entry_id" in st.session_state:
            st.session_state[selector_key] = st.session_state["last_entry_id"]

        selected_id = st.selectbox(
            "Select entry to audit",
            options=list(entry_options.keys()),
            format_func=lambda x: entry_options[x],
            key=selector_key
        )

        if selected_id:
            row = df[df["id"] == selected_id].iloc[0]
            try:
                st.image(base64.b64decode(row["file_path"]), use_container_width=True)
            except Exception:
                st.caption("Image data unavailable for this entry.")
    else:
        st.info("Upload a document to begin.")

# ── RIGHT COLUMN: Interactive Validation Matrix ──

with col2:
    st.subheader("Interactive Validation Matrix")
    if not df.empty:
        display_cols = [
            "id", "vendor_name", "transaction_date", "gross_amount",
            "currency", "ledger_category", "is_verified"
        ]

        column_config = {
            "id": st.column_config.TextColumn("ID", disabled=True, width="small"),
            "vendor_name": st.column_config.TextColumn("Vendor"),
            "transaction_date": st.column_config.TextColumn("Date"),
            "gross_amount": st.column_config.NumberColumn("Amount", format="%.2f"),
            "currency": st.column_config.SelectboxColumn("Currency", options=["HKD", "USD", "CNY", "EUR", "GBP", "SGD", "TWD"]),
            "ledger_category": st.column_config.TextColumn("Category"),
            "is_verified": st.column_config.CheckboxColumn("Verified"),
        }

        edited_df = st.data_editor(
            df[display_cols],
            column_config=column_config,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key="ledger_grid"
        )

        if st.button("Persist Changes", type="primary", use_container_width=True):
            update_entries(edited_df)
            verified_count = edited_df["is_verified"].sum()
            if int(verified_count) > 0:
                st.toast(f"{int(verified_count)} entries verified!")
            st.rerun()
    else:
        st.info("No entries in ledger. Upload a document above.")
