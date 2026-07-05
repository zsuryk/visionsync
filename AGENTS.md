# AI Developer Instructions (AGENTS.md)

## 1. Project Context & Mission
- **Project**: Vision Co Document-to-Books Data Pipeline
- **Role**: You are an expert Python engineer, specializing in rapid prototyping, Streamlit UI/UX, and LLM API integrations.
- **Mission**: Build a zero-friction, automated data extraction engine. The system must ingest mixed-language (English/Traditional Chinese) financial documents, parse them via a Multimodal LLM, log them locally, and render an interactive validation grid with linked source images.
- **Time Constraint**: This is a 5-hour hackathon build. Prioritize working, simple implementations over complex, abstracted architectures.

## 2. Technology Stack
- **Framework**: Streamlit (Python)
- **Database**: SQLite (Local file `db.sqlite`)
- **LLM Engine**: Multimodal Vision LLM via Tokenmart Inference API.
- **Dependency Management**: `uv`

## 3. Architectural Rules & Constraints
- **Single-File Monolithic Priority**: To eliminate networking overhead, keep all UI logic, state management, and API calls within a unified Streamlit runtime (e.g., `app.py`). 
- **NO Docker / NO Microservices**: Do not generate Dockerfiles, `docker-compose.yml`, or separate frontend/backend repositories. Do not introduce CORS or port-forwarding complexities.
- **Secrets Management**: NEVER hardcode API keys. Always retrieve credentials using `st.secrets["INFERENCE_AI_API_KEY"]`. Expect secrets to be stored in `.streamlit/secrets.toml`.
- **Stateless/Stateful Sync**: Use Streamlit's `st.session_state` to handle immediate UI reactivity, but persist all finalized ledger rows into the SQLite database.

## 4. Data Contracts & Schemas

### 4.1. LLM Extraction Schema
All API calls to the Inference AI must enforce a strict `json_object` response format. The system prompt must demand the following exact JSON structure, without markdown wrappers:
```json
{
  "vendor_name": "string (Supports English and Traditional Chinese)",
  "transaction_date": "string (Strict ISO-8601 Format: YYYY-MM-DD)",
  "gross_amount": "float (Normalized numeric value, no currency symbols)",
  "currency": "string (Standard 3-letter currency code, e.g., HKD, USD)",
  "ledger_category": "string (Standard operating bucket)"
}

```

### 4.2. SQLite Database Schema

The system must automatically initialize `db.sqlite` on startup if it does not exist, using the following schema for the `ledger_entries` table:

* `id`: string (UUID, Primary Key)
* `file_path`: string (Relative path or base64 pointer to the original uploaded document)
* `vendor_name`: string
* `transaction_date`: string
* `gross_amount`: float
* `currency`: string
* `ledger_category`: string
* `is_verified`: boolean (Default: False)
* `is_deleted`: boolean (Default: False) — soft-delete flag; records are never physically removed

## 5. UI / UX Implementation Guidelines

* **Audit Transparency (Critical)**: The UI must utilize Streamlit columns (`st.columns()`). When a parsed ledger entry is displayed or edited, the original uploaded image MUST be rendered directly adjacent to the data using `st.image()`.
* **Interactive Data Grid**: Use `st.data_editor()` to display the SQLite records, allowing the user to manually correct any LLM hallucinations.
* **Verification Hook**: Include a mechanism (like a checkbox column) to flip the `is_verified` boolean in the database, demonstrating the human-in-the-loop accounting workflow.

### 5.2. Multi-File Upload

* The sidebar file uploader uses `accept_multiple_files=True` to allow batch uploads of images and PDFs.
* Files are processed **one at a time per rerun** to allow interactive duplicate review between extractions. A `processed_keys` set deduplicates by `"{name}_{size}"` within the current upload batch; a `discarded_keys` set prevents re-extracting files the user chose to reject.
* When all files in a batch are processed/discarded, both sets are cleared and the `upload_counter` increments to reset the uploader widget.
* `st.session_state["pending_files"]` is not used — the uploader widget retains the file list natively; the sidebar picks the first unprocessed file each rerun.
* Warnings from all files are aggregated into `st.session_state["last_warnings"]` and displayed with a `"filename: message"` prefix.

### 5.3. Content-Based Duplicate Detection

* After LLM extraction, the extracted fields are compared against all non-deleted entries in the database using a weighted composite score:

| Field | Weight | Comparison Method |
|-------|--------|-----------------|
| vendor_name | 30% | `rapidfuzz.partial_ratio` |
| gross_amount | 30% | Numeric proximity: `1 - \|a-b\| / max(\|a\|,\|b\|)` |
| transaction_date | 20% | Exact = 100, ±7d = 80, ±30d = 50, else 0 |
| currency | 10% | Exact match |
| ledger_category | 10% | `rapidfuzz.partial_ratio` |

* If `composite >= 60`, the existing entry is flagged as a potential duplicate. Top 5 candidates (sorted descending by score) are stored in `st.session_state["dup_review"]`.
* The entry is **not inserted** until the user resolves all candidates via a `@st.dialog(width="large")` modal.
* The dialog shows side-by-side image previews (new vs. existing) with extracted JSON data.
* Below the comparison: **🗑 Discard Upload** (rejects the new entry, adds file key to `discarded_keys`) and **→ Continue Upload** (inserts the new entry).
* Candidates are processed sequentially — one dialog at a time. After all decisions are collected, the entry is inserted (if any "continue") or discarded (if all "discard").

### 5.5. Soft-Delete Convention

* Records are never physically deleted from the database. The `is_deleted` column (boolean, default `False`) marks an entry as removed.
* A **"🗑 Delete entry"** button appears beneath the source image in the Source Asset Vault column. Clicking it toggles `is_deleted` to `1` and hides the entry from the default view.
* The **"Show deleted records"** checkbox above the search box reveals deleted entries (with a 🗑 label). When viewing a deleted entry, the button reads **"↩ Restore entry"** — clicking it flips `is_deleted` back to `0`.
* The helper function `toggle_deleted(entry_id)` in `app.py` atomically flips the boolean using a `CASE WHEN` SQL statement.

## 6. Execution Commands

When asked to build, run, or test, assume the following environment commands:

* **Run**: `uv run streamlit run app.py`

## 7. AI Agent Directives

* **Plan Before Coding**: Before making substantial changes, briefly output the steps you will take to ensure they align with the single-file constraint.
* **Error Handling**: Gracefully handle JSON parsing errors (e.g., `json.JSONDecodeError`) from the LLM. If the LLM returns malformed data, surface a clean warning in the Streamlit UI rather than crashing the application.
