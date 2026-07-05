# VisionSync — Document-to-Books Pipeline

**Drop in messy receipts. Get clean ledger entries. Source-linked, human-verified, AI-powered.**

Built for **Vision Co** and every Hong Kong accounting firm drowning in paper — handles mixed Chinese/English, phone photos, PDF scans, and real-world document mess.

---

## Quick Start (30 seconds)

### Prerequisites
- Python 3.14+
- [`uv`](https://docs.astral.sh/uv/) (package manager — install once: `curl -LsSf https://astral.sh/uv/install.sh | sh`)

### Setup

```bash
# 1. Clone and enter the project
git clone <repo-url> && cd visionsync

# 2. Install dependencies
uv sync

# 3. Configure your Inference AI API key
mkdir -p .streamlit
echo 'INFERENCE_AI_API_KEY = "sk-inf-v1-your-key-here"' > .streamlit/secrets.toml

# 4. Launch!
uv run streamlit run app.py
```

That's it. The app opens in your browser at `http://localhost:8501`.

---

## How It Works (90-Second Tour)

1. **Upload** — Drag any mix of receipts, invoices, and PDFs (English, Chinese, or both) into the sidebar. Accepts `png`, `jpg`, `jpeg`, `pdf`.

2. **Extract** — The AI reads each document and extracts: vendor name, transaction date, gross amount, currency, and ledger category — all in structured JSON.

3. **Review** — The two-column split-screen shows the original document beside the extracted data. Toggle checkboxes to verify each row.

4. **Correct** — Edit any field directly in the data grid. The UI is a spreadsheet you can actually use.

5. **Persist** — Click "Persist Changes" to save edits and verifications to the local SQLite database.

---

## Key Features (For Judges)

| Feature | What it does |
|---------|-------------|
| **Mixed-language OCR** | Handles English + Traditional Chinese in the same document |
| **Messy input tolerance** | Phone photos, scanned PDFs, WeChat screenshots — all work |
| **Source-linked auditing** | Every entry is displayed beside its original document image |
| **Interactive data grid** | Edit, verify, and correct extracted data in-place |
| **Content-based deduplication** | Detects when the same invoice was uploaded twice via weighted field comparison |
| **AI Assistant** | Ask natural-language questions about your ledger (e.g., "What did we spend in July?") |
| **Soft-delete** | Mark entries as deleted without losing history — toggle via the grid |
| **Zero infrastructure** | Single file, local SQLite, no Docker, no cloud deployment needed |

---

## Tech Stack

- **Frontend/App**: [Streamlit](https://streamlit.io) (Python)
- **Database**: SQLite (local `db.sqlite`, auto-created on first run)
- **AI Engine**: Multimodal Vision LLM via [Tokenmart Inference API](https://model.service-inference.ai)
- **Dependencies**: `uv`-managed, 5 packages (streamlit, requests, pandas, PyMuPDF, rapidfuzz)

---

## Project Structure

```
visionsync/
├── app.py                  # Monolithic Streamlit app (all UI + logic)
├── .streamlit/
│   └── secrets.toml        # API key (gitignored — create your own)
├── pyproject.toml          # Python dependencies
├── requirements.txt        # pip-compatible dep list
├── AGENTS.md               # Architectural rules & schema docs
└── .gitignore
```
