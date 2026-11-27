# PersonaUX AI

**Test your website through every user's eyes.**

PersonaUX AI is an autonomous, AI persona-based UX and accessibility testing platform built with **Streamlit**, **Playwright (Chromium)**, **Google Gemini (`google-genai`)**, **axe-core (`axe-playwright-python`)**, **SQLAlchemy**, and **ReportLab**.

Traditional functional QA confirms that features work, but misses real human usability problems—confusion, hesitation, trust concerns, accessibility barriers, and mid-journey abandonment. PersonaUX AI places diverse AI-simulated user personas inside real, sandboxed Chromium browser contexts configured with their physical and cognitive constraints, records step-by-step screenshots and telemetry, runs automated WCAG and keyboard audits, and generates prioritized UX findings and PDF reports.

---

## Key Features

- **Research-Based & Custom Persona Library**
  - Includes **6 predefined personas** (`Sarah`, `Robert`, `Alex`, `Maria`, `David`, `Emily`) plus full CRUD for custom personas.
  - Configurable traits: `tech_confidence` (1–5), `patience` (1–10), `interaction_mode` (`mouse`, `keyboard`, `mixed`), `text_zoom` (100%–200%), `prefers_high_contrast`, and `language_level` (`native`, `intermediate`, `basic`).
- **Real Browser Physics & Interaction Simulation**
  - Browser zoom adjusts CSS viewport dimensions and `device_scale_factor` to emulate real browser zoom.
  - High-contrast personas enable `contrast="more"` and `forced_colors="active"`; keyboard/low-patience personas enable `reduced_motion="reduce"`.
  - **Keyboard-only mode** actually navigates using `Tab` presses (up to `MAX_TAB_PRESSES = 80`) and `Enter`/`Space`, surfacing unreachable controls and focus traps.
- **Dual-Layer UX Friction Detection (`Verified` + `AI-Inferred`)**
  - **Objective browser-verified checks** (no LLM): HTTP/JS/network errors, slow loads, dead-end pages (`0` interactive controls), oversized forms (`> 8` inputs), `< 24px` touch/click targets, `< 12px` font sizes, Flesch Reading Ease (`< 50`) for non-native English personas, unnamed controls, repeated actions (`>= 3`), and journey abandonment.
  - **AI-inferred persona evaluation**: Gemini evaluates the recorded step log and screenshots, strictly filtered by `validate_ai_findings()` so every AI finding is anchored to a real `step_number`, screenshot, and quoted evidence.
- **Automated Accessibility & Keyboard Auditing**
  - Runs **axe-core** (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`, `best-practice`) on visited paths (up to `MAX_AXE_SCANS_PER_PERSONA`).
  - Runs a custom `keyboard_audit` probing `Tab` reachability (`keyboard-no-focusable`), focus traps (`keyboard-focus-trap`), missing focus indicators (`focus-not-visible`), and off-screen focus (`focus-offscreen`).
- **7-Page Interactive Streamlit UI**
  - **Dashboard**, **New UX Test**, **Live Execution** (2-second auto-refreshing replay with live log & screenshots), **Test Results**, **Persona Reports**, **Overall Report** (cross-persona comparisons & executive synthesis), and **Persona Library**.
- **Automated PDF Reports**
  - Generates downloadable individual persona PDFs (with step-by-step screenshot timelines) and combined multi-persona executive PDFs into `artifacts/reports/`.
- **Security & Safety Guardrails**
  - SSRF/private-network IP & hostname validation (`security.py`), same-domain Playwright route confinement, irreversible action blocking (`UNSAFE_PATTERNS`), and automatic test-credential substitution.

---

## How the Agent Loop Works

Each test run launches a background daemon thread (`agents/test_runner.py`) and one headless Chromium instance (`automation/browser_manager.py`). Every selected persona runs independently through `PersonaAgent.run_journey()` (`agents/persona_agent.py`):

1. **Setup & Initial Audits**: Creates an isolated `BrowserContext`, navigates to the target URL, captures `step_01.jpg`, runs `AxeScanner.scan()`, and runs `keyboard_audit()` for `keyboard`/`mixed` personas.
2. **OBSERVE** (`automation/dom_inspector.py`): Injects `EXTRACT_JS` to tag up to `70` visible interactive elements with `data-pux-id`, collecting headings, alerts, forms, target sizes, font sizes, and a visible text excerpt (`DomSnapshot`).
3. **PLAN** (`agents/journey_planner.py` + `agents/gemini_client.py`): Sends the persona profile, journey goal, recent history, `DomSnapshot` (up to `60` elements), technical errors, and current JPEG screenshot to Gemini (`gemini-3.5-flash` with automatic fallback models), receiving a Pydantic-validated `PlannedAction` (`navigate`, `click`, `fill`, `select`, `scroll`, `press`, `wait`, `back`, `done`, or `abandon`).
4. **VALIDATE + ACT** (`agents/journey_planner.py` + `automation/playwright_executor.py`): `validate_action()` checks element validity, key allowlists, and domain boundaries; `PlaywrightExecutor` executes the action honoring the persona's `interaction_mode` and safety policies.
5. **CAPTURE**: Waits for page stabilization, takes a JPEG viewport screenshot, logs console/network errors, persists `ExecutionStep` + `Screenshot` to SQLite, and re-runs `axe-core` if a new path was visited. Loops until `done`, `abandon`, repeated-action loop detection (`repeat >= 2`), patience exhaustion (`round(patience / 2)` consecutive failures), or `max_steps`.
6. **EVALUATE & REPORT** (`agents/ux_analyzer.py` + `reports/report_generator.py`): Combines deterministic `objective_findings()` with Gemini's `evaluate_journey()`, calculates the `0–100` `experience_score`, synthesizes cross-persona recommendations (`OverallSynthesis`), and builds ReportLab PDFs.

---

## Predefined Personas

| Persona | Title | Tech Confidence | Patience | Interaction Mode | Zoom | Key Focus |
| --- | --- | --- | --- | --- | --- | --- |
| **Sarah** | First-Time User | 1/5 | 5/10 | Mouse | 100% | Simple navigation, clear labels, trust signals |
| **Robert** | Elderly User | 2/5 | 6/10 | Mouse | 150% | Large readable text, target sizes, contrast |
| **Alex** | Impatient Power User | 5/5 | 2/10 | Mixed (keyboard pref.) | 100% | Speed, minimal friction, shortcuts, reduced motion |
| **Maria** | Non-Native English Speaker | 3/5 | 6/10 | Mouse | 100% | Plain English (`basic` level), Flesch readability |
| **David** | Keyboard-Only User | 4/5 | 6/10 | Keyboard only (`Tab`) | 100% | Tab order, focus indicators, no keyboard traps |
| **Emily** | Low Vision User | 3/5 | 6/10 | Mouse | 200% | High contrast (`forced-colors`), layout reflow |

---

## Tech Stack

- **UI & Visualization**: `streamlit==1.67.0`, `plotly==7.2.0`, `pandas==3.1.1`
- **GenAI & Schemas**: `google-genai==3.6.1`, `pydantic==2.14.4`
- **Browser & Accessibility**: `playwright==1.65.2`, `axe-playwright-python==0.1.9`
- **Database & PDFs**: `sqlalchemy==2.1.9` (SQLite WAL mode by default), `reportlab==5.1.2`
- **Config & Testing**: `python-dotenv==1.2.4`, `pytest==9.2.0`

---

## Project Structure

```text
personaux-ai/
├── app.py                        # Streamlit entry point & navigation
├── config.py                     # Environment config, timeouts, viewports & test identity
├── database.py                   # SQLAlchemy engine, SQLite WAL pragmas, persona seeding & queries
├── models.py                     # ORM models (Project, Persona, TestRun, PersonaExecution, etc.)
├── security.py                   # URL normalization, SSRF/IP checks & domain allowlisting
├── requirements.txt              # Pinned Python dependencies
├── .env.example                  # Sample environment variables
├── .streamlit/config.toml        # Streamlit theme & server settings
├── accessibility/
│   └── axe_scanner.py            # axe-core WCAG scanner & FOCUS_PROBE_JS keyboard audit
├── agents/
│   ├── gemini_client.py          # Resilient google-genai wrapper with retry & model fallback
│   ├── journey_planner.py        # Multimodal persona planner & action validator
│   ├── persona_agent.py          # OBSERVE->PLAN->ACT->CAPTURE->EVALUATE loop & run_test()
│   ├── test_runner.py            # Daemon thread runner & LiveState event buffer
│   └── ux_analyzer.py            # Objective checks, Gemini evaluation & experience scoring
├── automation/
│   ├── browser_manager.py        # Chromium lifecycle, persona context options & network guard
│   ├── dom_inspector.py          # JS DOM extraction (data-pux-id) & page diagnostics
│   └── playwright_executor.py    # Mouse/keyboard action execution & safety guards
├── reports/
│   ├── report_generator.py       # Report aggregation, OverallSynthesis & PDF orchestration
│   └── pdf_generator.py          # ReportLab persona & combined PDF builders
├── ui/
│   ├── common.py                 # Shared styles, badges, finding & violation renderers
│   ├── dashboard.py              # KPIs, severity/persona charts & recent runs
│   ├── new_test.py               # Run configuration & URL authorization form
│   ├── execution.py              # Live 2s auto-refreshing execution monitor
│   ├── results.py                # Per-run persona cards & outcomes
│   ├── persona_reports.py        # Detailed 4-tab persona report & PDF download
│   ├── overall_report.py         # Cross-persona comparison, common issues & combined PDF
│   └── persona_library.py        # View predefined personas & manage custom personas
├── tests/
│   └── test_security.py          # Unit tests for URL validation & domain restrictions
└── artifacts/                    # Runtime SQLite DB, screenshots & generated PDF reports
```

---

## Setup & Installation

### 1. Prerequisites
- Python **3.11+** (tested with Python 3.12)
- A Google **Gemini API key**

### 2. Install Dependencies & Playwright Browser
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure Environment Variables
Create a `.env` file in `personaux-ai/` (you can start from `.env.example`):

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.5-flash
GEMINI_SEND_SCREENSHOTS=true
HEADLESS=true
DEFAULT_MAX_STEPS=15
HARD_MAX_STEPS=40
NAVIGATION_TIMEOUT_MS=30000
ACTION_TIMEOUT_MS=8000
SLOW_PAGE_THRESHOLD_MS=4000
MAX_AXE_SCANS_PER_PERSONA=5

# Dedicated test credentials substituted automatically into form fields
TEST_ACCOUNT_EMAIL=personaux.tester@example.com
TEST_ACCOUNT_NAME=Test User
TEST_ACCOUNT_PHONE=5550100123
```

> **Note:** Never commit real API keys or credentials to `.env.example` or `config.py`. Leave `TEST_ACCOUNT_PASSWORD` unset to generate a random password per process.

### 4. Run the Application
```bash
streamlit run app.py
```
Open the local URL printed by Streamlit (typically `http://localhost:8501`).

### 5. Run Tests
```bash
pytest
```

---

## Security & Responsible Testing

- **Public URLs Only**: `security.py` rejects `localhost`, `.local`/`.internal` domains, loopback/private/link-local/CGNAT IPs, cloud metadata endpoints (`169.254.169.254`, etc.), non-HTTP(S) schemes, and URLs with embedded credentials.
- **Domain Confinement**: Playwright intercepts all requests via `context.route("**/*", guard)`, blocking unsafe hosts and aborting top-level navigations outside the target site's domain.
- **Non-Destructive Execution**: `UNSAFE_PATTERNS` blocks clicks on controls related to purchasing, checkout, payment, donations, account deletion, or subscription cancellation.
- **Authorization Required**: The **New UX Test** form requires explicit confirmation that you own or are authorized to test the target website.

---

## Disclaimer

Automated accessibility checks (`axe-core` and keyboard focus heuristics) cover only a subset of WCAG success criteria and **do not establish full WCAG compliance**. Manual accessibility testing and assistive-technology verification remain essential.
