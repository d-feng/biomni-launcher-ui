# Biomni Launcher UI

A Tkinter desktop UI to run [Biomni](https://github.com/snap-stanford/Biomni) agentic biomedical workflows without a web server.

## Requirements

- Python 3.11+
- NVIDIA GPU recommended (CPU-only also works)
- Anthropic API key (or OpenAI / Gemini key)

## Setup

### 1. Configure API key

Create a `.env` file in this folder:

```
ANTHROPIC_API_KEY=your_key_here
```

### 2. Create virtual environment

**Windows:**
```bat
setup_venv.bat
```

**Linux:**
```bash
chmod +x setup_venv.sh
./setup_venv.sh
```

This installs all dependencies (biomni, langgraph, torch, pyarrow) into an isolated `venv/` folder.

## How to Run

**Windows:**
```bat
venv\Scripts\activate
python biomni_launcher.py
```

**Linux:**
```bash
source venv/bin/activate
python biomni_launcher.py
```

## Features

| Feature | Details |
|---------|---------|
| 4 preset prompts | Protein Expression, DEG & Pathway, Target Characterization, scRNA-seq Full Pipeline |
| Gene symbol field | Default `IFNG`, live substitution into prompt |
| Editable prompt | Freely edit before running |
| Model selector | Claude, GPT-4o, Gemini and more |
| Data directory | Browse to select Biomni data path |
| Timeout | Configurable in seconds (default 1200s) |
| Skip data lake | Checkbox to skip ~11GB download for testing |
| Data source manager | Add local paths or URLs, click to append to prompt |
| Live output | Scrollable terminal-style output panel |
| Log files | Saved to `~/biomni_logs/biomni_{GENE}_{timestamp}.txt` |
| Stop button | Terminate agent mid-run |

## Data Sources

Use the **Data Sources** panel to save frequently used datasets (local paths or URLs).
Click any entry to append it to the prompt text.
Sources are saved globally to `~/biomni_data_sources.json`.

## Logs

All run outputs are saved to:
```
~/biomni_logs/biomni_{GENE}_{timestamp}.txt
```
