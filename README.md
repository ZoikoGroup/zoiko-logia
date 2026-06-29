# ZoikoLogia

ZoikoLogia is a Streamlit prototype for an accounting intelligence platform powered by **Kriton**, a Groq-backed professional judgment assistant. The app combines a product-style dashboard, accounting learning tools, standards references, practice questions, workflow checklists, and a governed AI chat interface.

Kriton is designed for accounting, audit, tax, payroll, compliance, professional syllabus support, and ZoikoSuite workflow guidance. It changes its response style based on operating mode, risk level, and jurisdiction.

## Features

- Streamlit web app with landing, login, register, dashboard, reports, settings, and profile pages.
- Kriton chat assistant using the Groq API and `llama-3.3-70b-versatile`.
- Mode-aware AI responses for:
  - Learning: student-friendly explanations, examples, exam traps, and syllabus links.
  - Practice: standards references, journal entries, disclosures, and review points.
  - Workflow: short action lists for operational tasks.
  - Review: risk-rated conclusions, quality checks, and escalation triggers.
- Risk controls for low, medium, high, and restricted topics.
- Jurisdiction selector for international and local accounting, tax, and compliance context.
- Demo content for professional bodies, standards, worked examples, practice questions, jurisdictions, notifications, and reports.

## Project Structure

```text
zoiko-logia/
|-- app.py              # Main Streamlit application and page routing
|-- prompts.py          # Kriton system prompt and governance rules
|-- requirements.txt    # Python dependencies
|-- .env                # Local environment variables, not committed
|-- .gitignore          # Ignored local/runtime files
`-- README.md           # Project documentation
```

## Requirements

- Python 3.10 or newer
- A Groq API key

Python dependencies are listed in `requirements.txt`:

```text
streamlit
groq
python-dotenv
```

## Setup

1. Create and activate a virtual environment.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root.

```env
GROQ_API_KEY=gsk_your_key_here
```

The `.env` file is ignored by Git so local secrets are not committed.

## Run the App

Start Streamlit from the project directory:

```bash
streamlit run app.py
```

Streamlit will print a local URL, usually:

```text
http://localhost:8501
```

Open that URL in your browser.

## Using the Demo

- Visit the landing page to browse the product-style overview.
- Use **Register** or **Login** with any non-empty email and password to enter the dashboard.
- Open **Kriton Bot** from the floating chat button or by visiting `?page=Bot`.
- Configure Kriton from the sidebar:
  - Operating Mode
  - Risk Level
  - Jurisdiction
- Ask an accounting, audit, tax, payroll, compliance, or professional learning question.

If `GROQ_API_KEY` is missing, the Bot page will show an error and the rest of the demo pages will still load.

## App Pages

- Landing
- Login
- Register
- Dashboard
- Learning Center
- Standards Library
- Worked Examples
- Practice Questions
- Workflow Assistant
- Jurisdiction Center
- Source Explorer
- Saved Chats
- Reports
- Notifications
- Profile
- Settings
- Admin Panel
- Bot

Some pages are intentionally demo-only and use in-memory sample data.

## Authentication Notes

This prototype does not include a real authentication backend. Login and registration store user state only in the current Streamlit session.

The Admin Panel is guarded by `st.session_state.is_admin`, which currently defaults to `False`. There is no UI flow yet for making a user an admin.

## AI Governance Notes

Kriton's behavior is controlled by `SYSTEM_PROMPT` in `prompts.py`. The prompt defines:

- Supported professional domains.
- Mode-specific answer formats.
- Risk-level restrictions.
- Jurisdiction handling rules.
- Guardrails against unsupported professional advice.
- Escalation requirements for high-risk and restricted topics.

The app injects the user's selected mode, risk level, and jurisdiction into each chat request before sending it to Groq.

## Current Limitations

- Data is not persisted between sessions.
- Authentication is mocked.
- Standards, examples, practice questions, reports, and notifications are sample content.
- No database or document ingestion pipeline is included.
- No automated tests are currently included.
- The AI assistant depends on Groq API availability and a valid API key.

## Development Notes

- Main page routing is handled in `main()` inside `app.py`.
- Session defaults are initialized in `init_session()`.
- The non-chat pages use `MAIN_APP_STYLES`.
- The Bot page uses `BOT_PAGE_STYLES` and a dedicated sidebar/chat layout.
- Groq client creation is cached with `@st.cache_resource`.

## Disclaimer

ZoikoLogia and Kriton are a prototype and are not a substitute for a licensed accountant, tax adviser, auditor, attorney, or other qualified professional. High-risk or jurisdiction-specific matters should be reviewed by an appropriate professional before filing, signing, submitting, or relying on the output.
