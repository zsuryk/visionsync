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
* Duplicate detection: `st.session_state["processed_keys"]` (a `set` of `"{name}_{size}"` strings) prevents re-processing the same file across reruns.
* Each file in the batch is processed sequentially in a `for` loop; failed files (LLM returns `None`) are skipped silently.
* Warnings from all files are aggregated into `st.session_state["last_warnings"]` and displayed with a `"filename: message"` prefix.

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
