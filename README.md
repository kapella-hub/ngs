# NGS - NoiseGate Service

**Enterprise-grade alert noise reduction and incident correlation platform**

NGS ingests alerts from multiple monitoring systems via email (IMAP), normalizes them, deduplicates noise, correlates alerts into incidents, and provides AI-powered enrichment with suggested fixes.

## Features

- **Multi-source Alert Ingestion**: Monitor IMAP folders for alerts from OP5, Nagios, Xymon, Splunk, Prometheus, Zabbix, and more
- **LLM Learning Parser**: Self-learning parser that uses local Mistral 7B LLM to automatically learn new alert formats
- **Intelligent Deduplication**: Fingerprint-based correlation reduces alert noise
- **Incident Management**: Track, acknowledge, resolve, and suppress incidents
- **Maintenance Windows**: Auto-detect from email/calendar invites, suppress matching alerts
- **Knowledge Base**: Built-in RAG system for document search, runbooks, and suggested fixes
- **Modern Web UI**: React-based dashboard for triage, operations, and knowledge base chat

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   IMAP Server   │────▶│   ngs-worker     │────▶│   PostgreSQL    │
│ (Email Alerts)  │     │ (Ingestion/Parse)│     │   (Data Store)  │
└─────────────────┘     └────────┬─────────┘     └────────┬────────┘
                                 │                        │
                                 ▼                        ▼
                        ┌──────────────────┐     ┌─────────────────┐
                        │   RAG Service    │◀───▶│    ngs-api      │
                        │ (Mistral 7B LLM) │     │   (REST API)    │
                        │ (Pattern Cache)  │     └────────┬────────┘
                        └──────────────────┘              │
                                 ▲                        ▼
                                 │               ┌─────────────────┐
                                 └───────────────│  ngs-frontend   │
                                                 │   (React UI)    │
                                                 │ (Knowledge Base)│
                                                 └─────────────────┘
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- IMAP email account with folder access

### 1. Clone and Configure

```bash
git clone <repository-url>
cd ngs

# Create environment file
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# Required: IMAP Configuration
IMAP_HOST=imap.example.com
IMAP_USER=alerts@example.com
IMAP_PASSWORD=your_password
IMAP_FOLDERS=INBOX,OP5,XYMON,Splunk,MAINTENANCE

# Change in production
POSTGRES_PASSWORD=strong_password_here
JWT_SECRET=generate_a_secure_secret
```

### 2. Start Services

```bash
# Start all services (with RAG mock for development)
docker-compose --profile dev up -d

# Or without RAG mock
docker-compose up -d
```

### 3. Access the UI

Open http://localhost:3000 in your browser.

Default credentials: `admin` / `admin123`

## Project Structure

```
ngs/
├── backend/           # FastAPI REST API
│   ├── app/
│   │   ├── routers/   # API endpoints
│   │   ├── schemas/   # Pydantic models
│   │   └── services/  # Business logic
│   └── Dockerfile
├── worker/            # Background worker
│   ├── worker/
│   │   ├── imap_poller.py      # Email ingestion
│   │   ├── parser.py           # Alert parsing (regex + LLM)
│   │   ├── llm_parser.py       # LLM learning parser
│   │   ├── correlator.py       # Incident correlation
│   │   ├── maintenance_engine.py
│   │   └── rag_client.py       # AI enrichment
│   └── Dockerfile
├── frontend/          # React UI
│   ├── src/
│   │   ├── pages/     # Page components
│   │   │   ├── KnowledgeBasePage.tsx  # RAG chat UI
│   │   │   └── DocumentsPage.tsx      # Doc management
│   │   ├── components/
│   │   └── services/  # API clients
│   └── Dockerfile
├── rag/               # Local RAG service
│   ├── app/           # FastAPI RAG application
│   ├── static/        # RAG UI (standalone)
│   └── Dockerfile     # Includes Mistral 7B model
├── migrations/        # SQL migrations
│   ├── 001_initial.sql
│   └── 002_pattern_cache.sql  # LLM pattern cache
├── configs/           # YAML configuration
│   ├── parsers.yml    # Alert parsing rules
│   ├── correlation.yml
│   └── maintenance.yml
├── rag-mock/          # Mock RAG service (dev)
├── docker-compose.yml
└── .env.example
```

## Configuration

### Parser Configuration (`configs/parsers.yml`)

Define parsing rules for different alert sources:

```yaml
parsers:
  op5:
    name: "OP5 Monitor"
    subject_pattern: '\*\*\s*(?P<state>PROBLEM|RECOVERY)\*\*.*Host:\s*(?P<host>\S+)'
    body_patterns:
      - 'Service:\s*(?P<service>.+?)(?:\n|$)'
      - 'State:\s*(?P<severity>CRITICAL|WARNING|OK)'
```

### Correlation Configuration (`configs/correlation.yml`)

Configure deduplication and incident management:

```yaml
deduplication:
  window_minutes: 10

correlation:
  single_open_per_fingerprint: true
  auto_resolve:
    enabled: true
    hours_without_events: 24
```

### Maintenance Configuration (`configs/maintenance.yml`)

Configure maintenance window detection:

```yaml
detection:
  subject_prefixes:
    - "[MW]"
    - "Maintenance:"
  body_patterns:
    scope: 'Scope:\s*(.+?)(?:\n|$)'
    mode: 'Mode:\s*(mute|downgrade|digest)'
```

## API Reference

### Incidents

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/incidents` | GET | List incidents with filters |
| `/api/incidents/{id}` | GET | Get incident details |
| `/api/incidents/{id}/ack` | POST | Acknowledge incident |
| `/api/incidents/{id}/resolve` | POST | Resolve incident |
| `/api/incidents/{id}/suppress` | POST | Suppress incident |
| `/api/incidents/{id}/comment` | POST | Add comment |

### Maintenance

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/maintenance` | GET | List maintenance windows |
| `/api/maintenance` | POST | Create maintenance window |
| `/api/maintenance/{id}` | PATCH | Update maintenance window |
| `/api/maintenance/active` | GET | Get currently active windows |

### Admin

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/config/{type}` | GET | Get configuration |
| `/api/admin/ingestion/status` | GET | Get ingestion status |
| `/api/admin/stats/overview` | GET | Get system statistics |
| `/api/admin/audit-log` | GET | Get audit log |

## Data Model

### Core Entities

- **raw_emails**: Immutable store of ingested emails
- **alert_events**: Normalized events parsed from emails
- **incidents**: Correlated alert clusters
- **maintenance_windows**: Scheduled maintenance periods
- **suppression_rules**: Manual suppression rules

### Incident Lifecycle

```
┌──────┐    ┌──────────────┐    ┌──────────┐
│ open │───▶│ acknowledged │───▶│ resolved │
└──────┘    └──────────────┘    └──────────┘
    │              │                  ▲
    │              │                  │
    └──────────────┴──────────────────┘
                   │
                   ▼
            ┌────────────┐
            │ suppressed │
            └────────────┘
```

## Maintenance Windows

### Email-based Detection

NGS detects maintenance windows from emails with:
- Subject prefixes: `[MW]`, `Maintenance:`
- ICS calendar attachments (Outlook invites)
- Structured body content

Example email body:
```
Title: Database Maintenance
Scope: host=db-*; service=mysql; env=prod
Mode: mute
Start: 2024-01-15 02:00
End: 2024-01-15 06:00
Timezone: UTC
```

### Suppression Modes

| Mode | Behavior |
|------|----------|
| **mute** | No notifications, events still stored |
| **downgrade** | Lower severity for routing |
| **digest** | Include in periodic digest only |

## LLM Learning Parser

NGS includes a self-learning parser powered by a local Mistral 7B LLM. When a new alert format is encountered, the LLM extracts fields and generates reusable regex patterns that are cached for future use.

### How It Works

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  New Email      │────▶│ Compute Signature│────▶│ Check Pattern   │
│  Arrives        │     │ (hash of format) │     │ Cache           │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                        ┌─────────────────────────────────┼─────────────────────────────────┐
                        │                                 │                                 │
                        ▼                                 ▼                                 │
                ┌───────────────┐                 ┌───────────────┐                        │
                │ Cache HIT     │                 │ Cache MISS    │                        │
                │ Apply cached  │                 │ Call Mistral  │                        │
                │ regex rules   │                 │ LLM to parse  │                        │
                │ (fast, no LLM)│                 │ & learn rules │                        │
                └───────┬───────┘                 └───────┬───────┘                        │
                        │                                 │                                 │
                        │                                 ▼                                 │
                        │                         ┌───────────────┐                        │
                        │                         │ Cache new     │                        │
                        │                         │ pattern       │────────────────────────┘
                        │                         └───────┬───────┘
                        │                                 │
                        └─────────────────┬───────────────┘
                                          ▼
                                  ┌───────────────┐
                                  │ Extracted:    │
                                  │ host, service │
                                  │ severity,state│
                                  └───────────────┘
```

### Signature Computation

Emails are grouped by format signature based on:
- **From domain**: e.g., `xymon-alerts.company.com`
- **Subject prefix**: First 50 chars normalized (numbers → `*N*`, dates → `*DATE*`)
- **Body markers**: Key phrases like `severity`, `host:`, `critical`, etc.

### Configuration

```bash
# Enable/disable LLM parsing (default: enabled)
LLM_PARSING_ENABLED=true

# LLM endpoint (points to RAG service)
LLM_ENDPOINT=http://rag:8001
```

### Pattern Cache

Learned patterns are stored in `pattern_cache` table:
- `signature_hash` - SHA256 hash of format signature
- `extraction_rules` - JSON regex patterns for each field
- `match_count` - How many emails used this pattern
- `success_rate` - Extraction accuracy percentage

## Knowledge Base (RAG)

NGS includes a built-in knowledge base powered by the same Mistral 7B LLM used for parsing. Upload runbooks, documentation, and troubleshooting guides to get AI-powered suggestions.

### Features

- **Document Upload**: Support for PDF, DOCX, TXT, MD, HTML, images (with OCR)
- **URL Ingestion**: Crawl web pages and documentation sites
- **Vector Search**: ChromaDB-powered semantic search
- **Chat Interface**: Ask questions about your documentation

### Accessing the Knowledge Base

1. Navigate to **Knowledge Base** in the sidebar
2. Upload documents via **Manage Docs**
3. Ask questions about your documentation

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | RAG service health check |
| `/stats` | GET | Document/chunk counts |
| `/ask` | POST | Ask a question |
| `/documents/upload` | POST | Upload files |
| `/documents/upload-url` | POST | Ingest from URL |
| `/documents/list` | GET | List all documents |
| `/documents/file/{name}` | DELETE | Delete a document |

## RAG Integration (Incident Enrichment)

NGS uses the RAG service for incident enrichment:

**Request:**
```json
{
  "incident": {
    "id": "...",
    "title": "...",
    "host": "...",
    "severity": "critical"
  },
  "events": [...]
}
```

**Response:**
```json
{
  "summary": "...",
  "category": "Database",
  "owner_team": "DBA Team",
  "recommended_checks": ["Check connection pool", "..."],
  "suggested_runbooks": [{"id": "...", "title": "...", "url": "..."}],
  "safe_actions": ["Clear idle connections"],
  "confidence": 0.85
}
```

## Observability

### Health Endpoints

- `GET /healthz` - Liveness check
- `GET /readyz` - Readiness check (includes DB)
- `GET /metrics` - Prometheus metrics

### Key Metrics

- `ngs_incidents_total` - Total incidents created
- `ngs_events_processed_total` - Events processed
- `ngs_emails_ingested_total` - Emails ingested
- `ngs_rag_request_duration_seconds` - RAG latency

### Logging

All services output structured JSON logs:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "info",
  "event": "incident_created",
  "incident_id": "...",
  "fingerprint": "..."
}
```

## Security

### Authentication

- JWT-based authentication
- Role-based access control (viewer, operator, admin)

### Best Practices

- Store secrets in environment variables only
- Use reverse proxy (nginx) with TLS in production
- Regularly rotate JWT secrets
- Enable audit logging

## Path to Production

### Phase 1: PoC (Complete)

- [x] IMAP email ingestion
- [x] Alert parsing and correlation
- [x] Maintenance window detection
- [x] RAG enrichment integration
- [x] Web UI for triage
- [x] LLM learning parser with pattern caching
- [x] Knowledge base with document management

### Phase 2: Production Ready

- [ ] Kubernetes deployment (Helm charts)
- [ ] Microsoft Graph calendar integration
- [ ] Webhook notifications (Slack, PagerDuty)
- [ ] SSO/SAML authentication
- [ ] Multi-tenant support
- [ ] GPU acceleration for LLM

### Phase 3: Self-Healing

- [ ] Action execution framework
- [ ] Approval workflows
- [ ] Ansible/Script integration
- [ ] Allowlists and safeguards

## Development

### Local Development

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev

# Worker
cd worker
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m worker.main
```

### Running Tests

```bash
# Backend tests
cd backend
pytest

# Frontend tests
cd frontend
npm test
```

## License

[Your License Here]

## Support

- GitHub Issues: [repository-url]/issues
- Documentation: [docs-url]
