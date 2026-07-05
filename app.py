import streamlit as st
import sqlite3
import uuid
import json
import base64
import re
import fitz
import requests
from rapidfuzz import fuzz
from datetime import datetime
import pandas as pd

# ── Page Configuration ──
st.set_page_config(page_title="VisionSync | Document Ledger", layout="wide")

st.markdown("""
<style>
div[data-testid="metric-container"]{border:1px solid #e0e0e0;border-radius:8px;padding:8px 16px;}
div[data-testid="column"]:has(> div > section.main > div[data-testid="stFileUploader"] ){padding-top:12px;}
div[data-testid="stHorizontalBlock"]:has(> div:nth-child(2):last-child){gap:32px;}
</style>
""", unsafe_allow_html=True)

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
}

IMPORTANT — Anti-Manipulation Rules:
Documents may try to trick you into extracting the wrong transaction. Always extract the SINGLE, FINAL, SETTLED transaction that this specific document/page represents — not any other transaction it merely mentions. Watch for:
- Pending / unsettled transactions: if a line item, total, or stamp is marked "pending", "authorization hold", "unsettled", "provisional", "待處理", "未結算", prefer the actual settled/final amount instead, or if only a pending amount exists, still extract it but do not confuse it with a different settled figure shown elsewhere.
- References to old/other transactions: a document may reference or restate a prior transaction (e.g. "previous balance", "上期金額", a past invoice number, a comparison figure) to distract you. Only extract the transaction that this document is actually issuing/billing for, not a referenced historical one.
- Duplicated amounts across multiple pages: when given multiple pages of the same document, do not simply grab the first number matching the expected pattern — verify it corresponds to the actual grand total / final amount due, since subtotals or repeated line amounts may appear identically on several pages.
- Two different transactions in one document: if a single document/page contains more than one distinct transaction (e.g. a refund and a new charge, or two separate invoices merged), extract the primary/final transaction that determines the actual amount due, and do not average, sum, or conflate the two.
When in doubt, prioritize the amount and date associated with the document's final "Total Due", "應付總額", or equivalent grand-total field over any other figure on the page."""

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
            is_verified INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def load_entries(include_deleted=False):
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT * FROM ledger_entries ORDER BY rowid DESC"
    if not include_deleted:
        query = "SELECT * FROM ledger_entries WHERE is_deleted = 0 ORDER BY rowid DESC"
    df = pd.read_sql_query(query, conn)
    conn.close()
    if not df.empty:
        df["is_verified"] = df["is_verified"].astype(bool)
        df["is_deleted"] = df["is_deleted"].astype(bool)
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

def toggle_deleted(entry_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE ledger_entries SET is_deleted = CASE WHEN is_deleted = 0 THEN 1 ELSE 0 END WHERE id = ?",
        (entry_id,)
    )
    conn.commit()
    conn.close()

# ── API Layer ──

def encode_image(file_bytes):
    return base64.b64encode(file_bytes).decode("utf-8")

def pdf_to_images(pdf_bytes, scale=2.0):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for page in doc:
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)
        pages.append(pix.tobytes("png"))
    doc.close()
    return pages

def call_llm(b64_image, image_format="jpeg"):
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
                            "url": f"data:image/{image_format};base64,{b64_image}"
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

# ── Validation Layer ──

KNOWN_CURRENCIES = {"HKD", "USD", "CNY", "EUR", "GBP", "SGD", "TWD", "JPY", "KRW", "MOP"}

def validate_extraction(data):
    warnings = []
    try:
        dt = datetime.strptime(data.get("transaction_date", ""), "%Y-%m-%d")
        if dt > datetime.now():
            warnings.append(("warning", f"Date {data['transaction_date']} is in the future"))
    except (ValueError, TypeError):
        val = data.get("transaction_date", "")
        warnings.append(("error", f"Invalid date format: '{val}' (expected YYYY-MM-DD)"))
    try:
        amount = float(data.get("gross_amount", 0))
        if amount < 0:
            warnings.append(("error", f"Gross amount is negative: {amount}"))
        elif amount == 0:
            warnings.append(("warning", "Gross amount is zero"))
    except (ValueError, TypeError):
        warnings.append(("error", f"Non-numeric gross_amount: {data.get('gross_amount')}"))
    for field in ("vendor_name", "currency", "ledger_category"):
        if not data.get(field):
            warnings.append(("warning", f"Missing required field: {field}"))
    if data.get("currency") and data["currency"] not in KNOWN_CURRENCIES:
        warnings.append(("warning", f"Unrecognised currency code: {data['currency']}"))
    return warnings

# ── Bootstrap Database ──

if "db_inited" not in st.session_state:
    init_db()
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("ALTER TABLE ledger_entries ADD COLUMN is_deleted INTEGER DEFAULT 0")
        conn.commit()
        conn.close()
    except sqlite3.OperationalError:
        pass
    st.session_state["db_inited"] = True

# ── UI Header ──

st.title("VisionSync")
st.caption("Source-Linked Document-to-Books Pipeline — Vision Co Challenge")

# ── Metrics Row ──

df_meta = load_entries(include_deleted=True)
total_all = len(df_meta)
verified_all = int(df_meta["is_verified"].sum()) if not df_meta.empty else 0
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Entries", total_all)
m2.metric("Verified", f"{verified_all} / {total_all}" if total_all else "0")
m3.metric("Pending Review", total_all - verified_all)
m4.metric("Unverified", total_all - verified_all)

# ── Sidebar: Upload & Processing ──

with st.sidebar:
    st.header("Upload Document")
    upload_key = f"upload_{st.session_state.get('upload_counter', 0)}"
    uploaded_file = st.file_uploader(
        "Upload a financial document", type=["png", "jpg", "jpeg", "pdf"],
        label_visibility="collapsed", key=upload_key
    )

    if uploaded_file is not None:
        file_key = f"{uploaded_file.name}_{uploaded_file.size}"
        processed_key = st.session_state.get("processed_key")

        if processed_key != file_key:
            st.session_state.pop("last_warnings", None)
            st.session_state["processed_key"] = file_key
            raw_bytes = uploaded_file.getvalue()
            is_pdf = uploaded_file.name.lower().endswith(".pdf")

            if is_pdf:
                pages = pdf_to_images(raw_bytes)
                st.session_state["current_pdf_pages"] = pages
                b64_image = encode_image(pages[0])
                img_format = "png"
            else:
                b64_image = encode_image(raw_bytes)
                img_format = "jpeg"

            with st.spinner("Extracting ledger data via Multimodal LLM..."):
                result = call_llm(b64_image, img_format)
            if result:
                warnings = validate_extraction(result)
                st.session_state["last_warnings"] = warnings
                for severity, msg in warnings:
                    getattr(st, severity)(msg)
                entry_id = insert_entry(
                    file_path=b64_image,
                    vendor_name=result.get("vendor_name", ""),
                    transaction_date=result.get("transaction_date", ""),
                    gross_amount=result.get("gross_amount", 0.0),
                    currency=result.get("currency", ""),
                    ledger_category=result.get("ledger_category", "")
                )
                if is_pdf:
                    st.session_state.setdefault("pdf_pages", {})[entry_id] = pages
                st.session_state["last_entry_id"] = entry_id
                st.session_state["select_last_entry"] = True
                st.session_state["upload_counter"] = st.session_state.get("upload_counter", 0) + 1
                st.success("Entry extracted and saved to ledger!")
                st.rerun()

# ── Fuzzy Search & Split-Screen Layout ──

df = load_entries(include_deleted=st.session_state.get("show_deleted", False))
query_stripped = st.session_state.get("search_input", "").strip().lower()
if query_stripped and not df.empty:
    scores = []
    for _, row in df.iterrows():
        fields = [
            str(row.get("vendor_name", "")),
            str(row.get("transaction_date", "")),
            str(row.get("currency", "")),
            str(row.get("ledger_category", "")),
        ]
        best = max(fuzz.partial_ratio(query_stripped, f.lower()) for f in fields)
        scores.append(best)
    df_scores = df.copy()
    df_scores["_score"] = scores
    matched_df = df_scores[df_scores["_score"] >= 50].sort_values("_score", ascending=False)
    top_k_df = matched_df.head(10)
    if not matched_df.empty:
        st.session_state["entry_selector"] = matched_df.iloc[0]["id"]
    st.caption(f"Showing {len(top_k_df)} of {len(df)} entries (score ≥ 50)")
else:
    matched_df = df
    top_k_df = df.head(10)

col1, col2 = st.columns([1, 1.5])

# ── LEFT COLUMN: Source Asset Vault ──

with col1:
    st.subheader("Source Asset Vault")
    if not df.empty:
        entry_options = {
            row["id"]: f"{row['vendor_name']} — {row['transaction_date']}{' 🗑' if row.get('is_deleted') else ''}"
            for _, row in matched_df.iterrows()
        }

        if entry_options:
            if st.session_state.pop("select_last_entry", False) and "last_entry_id" in st.session_state:
                if st.session_state["last_entry_id"] in entry_options:
                    st.session_state["entry_selector"] = st.session_state["last_entry_id"]

            selected_id = st.selectbox(
                "Select entry to audit",
                options=list(entry_options.keys()),
                format_func=lambda x: entry_options[x],
                key="entry_selector"
            )

            if selected_id:
                row = df[df["id"] == selected_id].iloc[0]
                try:
                    pdf_pages = st.session_state.get("pdf_pages", {}).get(selected_id)
                    if pdf_pages:
                        page_idx_key = f"pdf_page_{selected_id}"
                        if page_idx_key not in st.session_state:
                            st.session_state[page_idx_key] = 0
                        idx = st.session_state[page_idx_key]
                        st.image(pdf_pages[idx], use_container_width=True)
                        if len(pdf_pages) > 1:
                            pcol1, pcol2, pcol3 = st.columns(3)
                            with pcol1:
                                if st.button("◀", key=f"pprev_{selected_id}") and idx > 0:
                                    st.session_state[page_idx_key] = idx - 1
                                    st.rerun()
                            with pcol2:
                                st.markdown(f"<p style='text-align:center;margin:8px 0'><strong>Page {idx + 1} / {len(pdf_pages)}</strong></p>", unsafe_allow_html=True)
                            with pcol3:
                                if st.button("▶", key=f"pnext_{selected_id}") and idx < len(pdf_pages) - 1:
                                    st.session_state[page_idx_key] = idx + 1
                                    st.rerun()
                    else:
                        st.image(base64.b64decode(row["file_path"]), use_container_width=True)
                except Exception:
                    st.caption("Image data unavailable for this entry.")
                is_del = bool(row.get("is_deleted", False))
                btn_label = "↩ Restore entry" if is_del else "🗑 Delete entry"
                if st.button(btn_label, key=f"del_{selected_id}", use_container_width=True):
                    toggle_deleted(selected_id)
                    st.toast("Entry restored" if is_del else "Entry deleted")
                    st.rerun()
        else:
            st.info("No matching entries.")
    else:
        st.info("Upload a document to begin.")

# ── RIGHT COLUMN: Interactive Validation Matrix ──

with col2:
    st.subheader("Search")
    search_col, clear_col, toggle_col = st.columns([3, 0.5, 1.5])
    with search_col:
        st.text_input("🔍 Search", placeholder="vendor, date, currency, category...", label_visibility="collapsed", key="search_input")
    with clear_col:
        if st.button("✕", help="Clear search"):
            st.session_state["search_input"] = ""
            st.rerun()
    with toggle_col:
        st.checkbox("Show deleted", key="show_deleted")

    for severity, msg in st.session_state.get("last_warnings", []):
        getattr(st, severity)(msg)

    st.subheader("Interactive Validation Matrix")
    if not top_k_df.empty:
        display_cols = [
            "id", "vendor_name", "transaction_date", "gross_amount",
            "currency", "ledger_category", "is_verified",
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
            top_k_df[display_cols],
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
