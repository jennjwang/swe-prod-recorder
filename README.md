# SWE Productivity Recorder

A macOS screen activity recorder built on top of [gum](https://github.com/GeneralUserModels/gum) (Linux version coming soon!). It guides a participant through selecting the windows they are comfortable sharing and records high-signal screen activity around user interactions.

The project pairs a command-line facilitator (`cli.py`) with an asynchronous observer framework (`gum.py`) and a `Screen` observer that captures before/after screenshots, keyboard sessions, and mouse events.

## Architecture

- `cli.py` – argument parsing, participant briefing, and lifecycle orchestration.
- `gum.py` – async context manager that fans in updates from one or more observers and stores them as `observation` rows.
- `auth/` – authentication modules (Google Drive OAuth).
- `observers/` – concrete observer implementations. `screen` handles region selection, screenshot capture, scroll tracking, keyboard sessions, and inactivity detection.
- `models.py` – SQLAlchemy ORM + FTS5 schema for observations and derived propositions, plus async engine/session helpers.
- `schemas.py` – pydantic models describing the JSON update payloads and LLM-facing schemas.

## Requirements

- macOS 12 or later
- System permissions:
  - Screen Recording permission for your terminal
  - Accessibility permission for keyboard/mouse monitoring
  - Grant these in: System Settings → Privacy & Security
- Python 3.11 (3.10+ should work, but 3.11 is what the type hints target).
- Homebrew-installed `sqlite`/`libsqlite3` is recommended for the bundled FTS5 support.
- Python packages (installed automatically via pip)
- For Google Drive uploads: Create a `config/.env` file with OAuth credentials (see setup below)

### Installation

Install into a conda environment **(recommended)**:

```bash
conda create -n recorder python=3.11
conda activate recorder
pip install -e .
```

### Optional Features

**Google Drive uploads:**

```bash
pip install -e ".[gdrive]"
```

Adds: PyDrive, PyYAML, python-dotenv

## Usage

Run the recorder with:

```bash
swe-prod-recorder [OPTIONS]
```

```
usage: swe-prod-recorder [-h]
                         [--upload-to-gdrive]
                         [--record-all-screens | --all]
                         [--inactivity-timeout INACTIVITY_TIMEOUT]
                         --pr PR

SWE Productivity Recorder - Screen activity recorder for software engineer
productivity research

options:
  -h, --help            Show this help message and exit
  --upload-to-gdrive    Upload screenshots to Google Drive and delete local copies
  --record-all-screens, --all
                        Record all monitors/screens (no window selection needed). Default on Linux.
  --inactivity-timeout INACTIVITY_TIMEOUT
                        Stop recording after N minutes of inactivity (default: 45)
  --pr PR               PR number to organize screen recording data under data/pr_{pr} (required; use issue number if PRs are not available yet, or 0 for onboarding)
```

### Window Selection

When the recorder starts, you'll see an overlay for selecting which windows to record:

1. **Click on windows** to select them (they turn GREEN)
2. **Click selected windows again** to deselect them
3. **Press ENTER** or click the green DONE button to start recording
4. **Press Ctrl+C** to cancel

**IMPORTANT**: If you are running macOS Tahoe 26.X, please use the following command instead.

```bash
swe-prod-recorder --all
```

There is a known issue that leads the screen recorder to fail after the window selection in this OS version. This command will record your full screen during interactions, so please make sure to close all personal files prior to recording.

## Data Layout

- `config/` – Configuration files
  - `.env` – Your Google OAuth credentials (you provide this, gitignored)
  - `.google_auth/` – Auto-generated Google Drive authentication (gitignored)
    - `client_secrets.json` – Auto-generated from `config/.env`
    - `credentials.json` – Auto-generated OAuth tokens after authentication
- `data/` – Runtime data (gitignored)
  - `actions.db` – SQLite database with observations and propositions (WAL mode enabled)
  - `screenshots/` – Timestamped screenshots
    - **Without `--upload-to-gdrive`**: Stored locally and kept permanently
    - **With `--upload-to-gdrive`**: Uploaded to Google Drive and deleted locally
  - `pr_{N}/` – PR-specific directories (when using `--pr` flag)
    - `actions.db` – SQLite database for this pr
    - `screenshots/` – Screenshots for this pr

### Organizing Data by PR

The `--pr` flag is required to organize recordings by PR number (use issue number if PRs are not available yet, or 0 for onboarding):

```bash
swe-prod-recorder --pr 1
```

This saves all data under `data/pr_1/` instead of `data/`, making it easy to keep recordings from different PRs/issues separate. For onboarding sessions, use `--pr 0` which will save data under `data/pr_0/`. The directory structure will be:

```
data/
├── pr_1/
│   ├── actions.db
│   └── screenshots/
├── pr_2/
│   ├── actions.db
│   └── screenshots/
└── ...
```

You can inspect the database with:

```bash
sqlite3 data/actions.db '.tables'
# Or for a specific pr:
sqlite3 data/pr_1/actions.db '.tables'
```

## Google Drive Uploads

When using `--upload-to-gdrive`, screenshots are uploaded directly to Google Drive **instead of** being stored locally. This saves local disk space while keeping all recordings securely backed up in the cloud.

**How it works:**

1. We will provide: `config/.env` file with 3 credentials (CLIENT_ID, PROJECT_ID, CLIENT_SECRET)
2. Auto-generated: `config/.google_auth/client_secrets.json` created from your `.env` on first run
3. Auto-generated: `config/.google_auth/credentials.json` created after you authenticate in browser
4. Screenshots upload to Google Drive and are deleted locally

## Project Structure

```
recorder/
├── config/
│   ├── .env.example          # Template for Google OAuth credentials
│   └── .google_auth/         # Auto-generated (gitignored)
│       ├── client_secrets.json
│       └── credentials.json
├── data/                     # Runtime data (gitignored)
│   ├── actions.db
│   └── screenshots/
├── src/swe_prod_recorder/
│   ├── cli.py                # Command-line entry point
│   ├── gum.py                # Observer manager + database writer
│   ├── models.py             # SQLAlchemy ORM models
│   ├── schemas.py            # Pydantic schemas
│   ├── auth/                 # Authentication
│   │   └── google_drive.py   # Google Drive OAuth
│   └── observers/            # Recording logic
│       ├── screen.py         # Main screen observer
│       ├── window/           # Window selection
│       └── observer.py       # Base class
└── pyproject.toml            # Package configuration
```

## Attribution

This project is built on top of [GUM (General User Models)](https://github.com/GeneralUserModels/gum)
(MIT License) by Omar Shaikh.
The core observer pattern and database architecture are adapted from that project.

The Linux window manager and graphics integration were vendored from [pyx-sys](https://github.com/lmmx/pyx-sys)
(MIT License) by Louis Maddox.
