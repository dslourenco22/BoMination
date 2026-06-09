# BoMination — Server Deployment Proposal

## Overview

BoMination is an internal tool that extracts Bill of Materials (BOM) tables from PDF documents using a locally-hosted AI model (Ollama), and outputs organized Excel files including a pre-filled cost sheet. Currently it runs as a desktop application installed on individual machines. This document outlines what is required to host it on a company server so the purchasing team can access it through a web browser with no local installation.

---

## Why Server-Host It

| Local Install | Server-Hosted |
|---|---|
| Each user needs Python, Ollama, and all dependencies installed | One install, everyone accesses via browser |
| Each machine needs enough RAM for the AI model (~4 GB) | One powerful machine handles all requests |
| Updates must be pushed to every machine | Update once, all users get it immediately |
| Sales team needs a packaged .exe per update | No distribution needed |

---

## How It Works (for IT)

1. User uploads a PDF through a web page and specifies a page range (and optionally a company format)
2. The server extracts text from the PDF using **pdfplumber** (no internet required)
3. The text is passed to **Ollama**, a locally-running AI model — **no data ever leaves the company network**
4. The AI identifies and parses the BOM table
5. **If the user enables price lookup**, part numbers are searched on DuckDuckGo to find pricing (only part numbers are sent — no document content). This is a toggle in the UI and can be left off for speed or compliance.
6. The server generates the output Excel files (extracted BOM, BOM with prices, and the filled OMNI cost sheet) and returns download links to the user

---

## Server Requirements

### Minimum Specs
| Component | Minimum | Recommended |
|---|---|---|
| CPU | 8-core (e.g. Intel Xeon, AMD EPYC) | 16-core |
| RAM | 16 GB | 32 GB |
| Storage | 50 GB free | 100 GB free |
| GPU | Not required | Optional — dramatically speeds up AI inference |
| OS | Windows Server 2019+ or Ubuntu 20.04+ | Ubuntu 22.04 LTS |
| Network | Internal LAN access | Internal LAN + outbound HTTP for price lookup |

> **Note on speed:** Without a GPU, the AI model runs on CPU and takes approximately 30–90 seconds per page. With a dedicated GPU (e.g. NVIDIA RTX 3060 or better with 8 GB+ VRAM), this drops to under 5 seconds per page. A GPU is strongly recommended for production use.

---

## Software Stack Required

All of the following is free and open-source:

| Software | Purpose | Install |
|---|---|---|
| Python 3.10+ (3.12 recommended) | Application runtime | python.org |
| Ollama | Local AI model server | ollama.com |
| llama3.2 or llama3.2:1b | AI model for BOM extraction | `ollama pull llama3.2` |
| All Python packages | Listed in `requirements.txt` | `pip install -r requirements.txt` |
| Streamlit | Web interface layer | Included in requirements |

> Ollama runs entirely on the server. No AI data is sent to external services.

---

## Architecture (Server-Hosted)

```
[Purchasing Team Browser]
        │  HTTP (internal network only)
        ▼
[Company Server]
  ├── Streamlit Web App  (port 8501)
  │     ├── File upload UI
  │     ├── Page range / company selector
  │     └── Download links for output Excel files
  │
  ├── BoMination Pipeline
  │     ├── pdfplumber  (PDF text extraction)
  │     ├── Ollama API  (local, port 11434)
  │     │     └── llama3.2 model
  │     └── map_cost_sheet.py  (Excel cost sheet fill)
  │
  └── DuckDuckGo Search  (outbound, part numbers only)
```

---

## Deployment Steps (for IT)

### 1. Install Python
```bash
# Ubuntu
sudo apt update && sudo apt install python3.10 python3-pip -y

# Windows Server — download from python.org
```

### 2. Install Ollama and pull the model
```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2          # ~2 GB download, full quality
# OR for CPU-only servers:
ollama pull llama3.2:1b       # ~700 MB download, faster on CPU

# Start Ollama as a background service
ollama serve &
```

### 3. Clone the repo and install dependencies
```bash
git clone https://github.com/dslourenco22/BoMination
cd BoMination
pip install -r requirements.txt
```

### 4. Launch the web interface
```bash
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

Users then navigate to `http://<server-ip>:8501` from any browser on the internal network.

### 5. (Optional) Run as a persistent service
On Linux, create a systemd service so the app restarts automatically on reboot:
```ini
[Unit]
Description=BoMination BOM Tool
After=network.target

[Service]
ExecStart=/usr/bin/streamlit run /opt/bomination/app.py --server.port 8501 --server.address 0.0.0.0
WorkingDirectory=/opt/bomination
Restart=always
User=bomination

[Install]
WantedBy=multi-user.target
```

---

## Network / Firewall Requirements

| Direction | Protocol | Port | Purpose |
|---|---|---|---|
| Inbound (internal only) | TCP | 8501 | User browser access to the web app |
| Loopback | TCP | 11434 | App → Ollama (same machine, no network exposure) |
| Outbound | HTTPS | 443 | DuckDuckGo price search (part numbers only) |

> The Ollama port (11434) should **not** be exposed outside the server — it only needs to be reachable by the application on the same machine.

---

## Application Status (Development Work)

The **Streamlit web frontend is already built** — it lives at `app.py` in the repo root and is ready to deploy with `streamlit run app.py`. No further frontend development is required to launch.

The web interface provides:
- PDF file upload
- Page range input
- Company/customer selector dropdown (leave blank for automatic, format-agnostic extraction)
- **"Enable Live Price Lookup" toggle** — turn pricing on or off per run
- Live progress indicator while processing
- Side-by-side download buttons for the generated Excel files

Both frontends share the same pipeline code (`extract_main.py`, `map_cost_sheet.py`, `lookup_price.py`), which runs unchanged on the server:
- **`app.py`** — the Streamlit web app (this deployment)
- **`src/gui/BoMinationApp.py`** — the legacy desktop GUI, still used to build the standalone `.exe` for offline single-machine use

> The desktop `.exe` is **not** part of the server deployment — the server only runs the Streamlit app. The `.exe` remains available for users who need a fully offline, standalone tool.

---

## Security Considerations

- The web interface should be restricted to the **internal network only** (do not expose port 8501 to the internet)
- Uploaded PDFs are processed in memory and written to a temporary output directory — they are not stored permanently
- No PDF content or document text is sent outside the company network
- Only manufacturer part numbers are sent externally (to DuckDuckGo for pricing)
- Price lookup can be disabled per run via the **"Enable Live Price Lookup" toggle** in the UI — when off, no outbound web requests are made at all and cost columns are left blank

---

## Summary for Management

BoMination can be deployed on an existing company server with no licensing costs. The AI model runs fully on-premises — no document data leaves the network. Users access the tool through a standard web browser. The main IT ask is a server with at least 16 GB RAM and outbound internet access for price lookups. A GPU is optional but would significantly improve processing speed.
