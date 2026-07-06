# Ask Kriton™ Development Guide

## Table of Contents
1. [Overview](#overview)
2. [What is Ask Kriton](#what-is-ask-kriton)
3. [Data Flow Architecture](#data-flow-architecture)
4. [Data Requirements](#data-requirements)
5. [Data Source Options](#data-source-options)
6. [Implementation Phases](#implementation-phases)
7. [Quick Start Guide](#quick-start-guide)
8. [API Endpoints](#api-endpoints)

---

## Overview

**Ask Kriton™** is the core intelligence engine of ZoikoLogia. It answers governance and accounting questions by:
1. Retrieving relevant authoritative sources
2. Routing to appropriate AI model (Claude, GPT, Gemini)
3. Generating accurate, cited answers
4. Automatically logging decisions for audit compliance
5. Detecting and escalating high-risk answers

**Strategic Priority**: Build Ask Kriton FIRST — it generates all other dashboard data.

---

## What is Ask Kriton

### User Interface
```
User Input:
├─ Question: "What is going concern in IFRS?"
├─ Jurisdiction: [IFRS / US / UAE / UK / ...]
└─ Submit

Output:
├─ Answer: "Going concern is the assumption that..."
├─ Sources: [IFRS 1-10, FASB ASC 570, ...]
├─ Risk Level: [Low / High / Restricted]
└─ Audit Trail: [Link to audit replay]
```

### Key Features
- ✅ Source-governed (every answer traces to approved source)
- ✅ Jurisdiction-aware (different rules per jurisdiction)
- ✅ Risk-flagged (detects restricted outputs: audit opinions, tax advice)
- ✅ Fully auditable (complete decision trace logged)

---

## Data Flow Architecture

### Complete Pipeline

```
USER SUBMISSION
    ↓
    └─ Query: "What is going concern in IFRS?"
    └─ Jurisdiction: "IFRS"
    └─ User ID: "auditor-001"
    
    ↓ Frontend: POST /api/v1/rag/query
    
┌─────────────────────────────────────────────────────┐
│            BACKEND PROCESSING                        │
├─────────────────────────────────────────────────────┤
│                                                      │
│ 1. AUDIT LEDGER (logs request)                      │
│    ├─ Records query submission                      │
│    ├─ Records user, timestamp, jurisdiction        │
│    └─ Stores initial metadata                       │
│                                                      │
│ 2. RAG DOMAIN (retrieves sources)                   │
│    ├─ Converts query to vector embedding            │
│    ├─ Searches PostgreSQL + pgvector               │
│    ├─ Finds top-5 most relevant sources            │
│    └─ Returns sources with relevance scores        │
│                                                      │
│ 3. MODEL GATEWAY (routes to LLM)                    │
│    ├─ Applies jurisdiction routing policy          │
│    │  └─ IFRS → Claude                             │
│    │  └─ US → GPT-4                                │
│    │  └─ UAE → Gemini                              │
│    ├─ Constructs prompt with sources               │
│    ├─ Calls LLM API                                │
│    └─ Returns AI-generated answer                  │
│                                                      │
│ 4. RISK SAFETY (detects violations)                │
│    ├─ Scans answer for restricted patterns:        │
│    │  ├─ "audit opinion" → HIGH RISK               │
│    │  ├─ "tax advice/treatment" → HIGH RISK        │
│    │  ├─ "legal opinion" → HIGH RISK               │
│    │  └─ "specific filing action" → RESTRICTED     │
│    ├─ Assigns risk_level: Low / High / Restricted  │
│    ├─ If HIGH RISK: creates escalation             │
│    │  INSERT INTO escalations(...)                 │
│    └─ Blocks "Restricted" answers from release     │
│                                                      │
│ 5. AUDIT LEDGER (logs decision)                     │
│    ├─ Records final answer                         │
│    ├─ Records sources used                         │
│    ├─ Records risk assessment                      │
│    ├─ Records escalation (if created)              │
│    ├─ Records response time                        │
│    ├─ Records timestamp & provider used            │
│    └─ INSERT INTO ai_activities(...)               │
│                                                      │
└─────────────────────────────────────────────────────┘
    │
    ↓ Backend Response
    
RESPONSE TO FRONTEND
    ├─ {
    │   "success": true,
    │   "answer": "Going concern is...",
    │   "sources": [
    │     { "name": "IFRS 1-10", "text": "...", "url": "..." },
    │     { "name": "FASB ASC 570", "text": "...", "url": "..." }
    │   ],
    │   "risk_level": "Low",
    │   "escalation_id": null,
    │   "timestamp": "2026-07-06T10:30:00Z",
    │   "provider_used": "Claude"
    │ }
    │
    ↓ Frontend Display
    
USER SEES
    ├─ Answer with inline citations
    ├─ Risk indicator (✅ Safe / ⚠️ Review Required / 🔴 Escalated)
    ├─ Source links (clickable for full text)
    └─ Audit trail button (link to audit replay page)
```

---

## Data Requirements

### 1. SOURCES (Authoritative Reference Library)

**Definition**: Documents that Kriton uses to answer questions

**Database Model**:
```python
class Source(Base):
    __tablename__ = "sources"
    
    # Identity
    id: str                          # "src-001"
    name: str                        # "FASB ASC 570"
    content: str                     # Full text of standard
    
    # Embedding (for semantic search)
    embedding: Vector(1536)          # pgvector format
    content_hash: str                # For drift detection
    
    # Metadata
    source_type: str                 # "standard", "guidance", "policy"
    jurisdiction: str                # "US", "IFRS", "UAE"
    framework: str                   # "GAAP", "IFRS", "AICPA"
    
    # Licensing
    license_type: str                # "public", "subscription", "internal"
    license_expiry: datetime         # When license expires
    license_holder: str              # Who holds the license
    
    # Tracking
    url: str                         # Original source URL
    created_at: datetime
    updated_at: datetime
    last_verified: datetime
    
    # Governance
    approved_by: str                 # User who approved
    status: str                      # "Approved", "Pending", "Suspended"
    approval_date: datetime
    deprecation_note: str            # If deprecated
```

**Required for MVP**: Minimum 50-100 core sources

---

### 2. LLM MODEL CREDENTIALS

**What's needed**: API keys for AI models

**Options**:

#### Claude (Recommended for IFRS)
```env
ANTHROPIC_API_KEY=sk-ant-xxx
```
- Model: `claude-3-5-sonnet-20241022`
- Cost: ~$0.003 input, ~$0.015 output per 1K tokens
- Use for: Complex accounting concepts, IFRS questions

#### GPT-4 (Recommended for US)
```env
OPENAI_API_KEY=sk-xxx
```
- Model: `gpt-4-turbo`
- Cost: ~$0.01 input, ~$0.03 output per 1K tokens
- Use for: US regulations, tax questions

#### Gemini (Cost-effective fallback)
```env
GOOGLE_API_KEY=xxx
```
- Model: `gemini-2.0-pro`
- Cost: ~$0.0075 input per 1K tokens
- Use for: General queries, fallback

---

### 3. VECTOR EMBEDDINGS

**What's needed**: Convert text to vectors for semantic search

**Options**:

#### A. Sentence Transformers (Free, local)
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')
embedding = model.encode("Going concern is...")  # 384-dim vector
```
- Cost: Free
- Speed: ~10ms per embedding (local)
- Dimensions: 384

#### B. Anthropic Embeddings (Paid, high quality)
```python
response = client.embeddings.create(
    model="claude-3-5-embed",
    input="Going concern is..."
)
embedding = response.data[0].embedding  # 1024-dim
```
- Cost: $0.02 per 1M tokens
- Quality: High (tuned for enterprise)
- Dimensions: 1024

#### C. OpenAI Embeddings (Paid, industry standard)
```python
response = openai.Embedding.create(
    model="text-embedding-3-small",
    input="Going concern is..."
)
embedding = response.data[0].embedding  # 1536-dim
```
- Cost: $0.02 per 1M tokens
- Quality: High (industry standard)
- Dimensions: 1536

**Recommendation for MVP**: Use Sentence Transformers (free) → Later upgrade to Anthropic (better quality)

---

### 4. POSTGRESQL + PGVECTOR

**Requirements**:
```
PostgreSQL 14+ with pgvector extension
Database: zoikologia
Tables needed:
├─ sources (with embedding column)
├─ queries (questions asked)
├─ ai_activities (audit log)
├─ escalations (high-risk flags)
└─ source_drift_alerts
```

**Installation**:
```bash
# Mac
brew install postgresql
brew install pgvector

# Ubuntu
sudo apt-get install postgresql-14
sudo apt-get install postgresql-14-pgvector

# Or use Docker
docker run -d \
  -e POSTGRES_PASSWORD=password \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

**Enable extension**:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

---

## Data Source Options

### Option 1: Manual Seed (Fastest MVP)

**Effort**: 1-2 hours  
**Quality**: High  
**Best for**: Starting immediately

**Process**:
```python
# backend/scripts/seed_sources.py

CORE_SOURCES = [
    {
        "name": "IFRS 1-10 Going Concern",
        "content": "Going concern: the assumption that an entity will continue...",
        "jurisdiction": "IFRS",
        "source_type": "standard",
        "url": "https://www.ifrs.org/issued-standards/list-of-standards/ias-1-presentation-of-financial-statements/",
        "license_type": "public"
    },
    # ... add 20-50 more manually
]

# Run once:
python scripts/seed_sources.py
```

**Sources to manually add** (minimum 20):
- IFRS 1-15 (Core standards)
- FASB ASC 200-900 (Top accounting topics)
- AICPA Practice Aids (5-10 core)
- SEC Regulations (if US)
- Internal policies (if available)

---

### Option 2: API Integration (Official Sources)

**Effort**: 2-4 hours per source  
**Quality**: Official, always current  
**Best for**: Long-term maintenance

#### FASB Topics API
```python
# backend/scripts/import_fasb.py

import requests
from app.db.models import Source
from app.db.base import SessionLocal

def import_fasb_topics():
    """Fetch and import FASB Accounting Standards Codification"""
    
    # FASB provides REST API
    base_url = "https://www.fasb.org/cs/ContentServer"
    
    topics = [
        {"code": "205", "title": "Presentation of Financial Statements"},
        {"code": "210", "title": "Consolidated Financial Statements"},
        {"code": "220", "title": "Revenue Recognition"},
        # ... and ~80 more
    ]
    
    db = SessionLocal()
    
    for topic in topics:
        response = requests.get(
            f"{base_url}?c=Topic&cid=FASB_ASC_{topic['code']}&pagename=Viewcss"
        )
        
        source = Source(
            name=f"FASB ASC {topic['code']}",
            content=extract_text(response.text),
            jurisdiction="US",
            source_type="standard",
            license_type="public",
            url=response.url
        )
        
        db.add(source)
    
    db.commit()
    db.close()

# Run once:
# python scripts/import_fasb.py
```

#### IFRS Standards API
```python
# Similar structure for IFRS
# https://www.ifrs.org/issued-standards/list-of-standards/
```

#### AICPA Resources
```python
# AICPA has downloadable resources
# Some are free, some require subscription
```

---

### Option 3: PDF Upload Interface

**Effort**: 30 min per document + admin time  
**Quality**: Variable (depends on document)  
**Best for**: Custom/internal documents

**Backend endpoint**:
```python
# backend/app/domains/source_library/router.py

from fastapi import UploadFile, File, UploadFile
import pdfplumber

@router.post("/api/v1/sources/upload")
async def upload_source(
    file: UploadFile = File(...),
    jurisdiction: str = Query(...),
    current_user: User = Depends(get_current_user)
):
    """Admin uploads PDF source"""
    
    # Extract text from PDF
    content = ""
    with pdfplumber.open(file.file) as pdf:
        for page in pdf.pages:
            content += page.extract_text() + "\n"
    
    # Create source (pending approval)
    source = Source(
        name=file.filename.replace(".pdf", ""),
        content=content,
        jurisdiction=jurisdiction,
        source_type="custom",
        license_type="internal",
        status="Pending Review",  # Admin approves before use
        uploaded_by=current_user.id
    )
    
    db.add(source)
    db.commit()
    
    return {
        "source_id": source.id,
        "status": "Uploaded, awaiting admin approval"
    }
```

**Frontend**:
```typescript
// frontend/app/source-library/page.tsx

function UploadSourceForm() {
  const [file, setFile] = useState<File | null>(null);
  const [jurisdiction, setJurisdiction] = useState("IFRS");

  async function handleUpload(e: FormEvent) {
    if (!file) return;
    
    const formData = new FormData();
    formData.append("file", file);
    formData.append("jurisdiction", jurisdiction);
    
    const response = await fetch("/api/v1/sources/upload", {
      method: "POST",
      body: formData,
      credentials: "include"
    });
    
    const result = await response.json();
    alert(`Source uploaded: ${result.source_id}`);
  }

  return (
    <form onSubmit={handleUpload}>
      <input
        type="file"
        accept=".pdf"
        onChange={(e) => setFile(e.target.files?.[0] || null)}
      />
      <select value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)}>
        <option>IFRS</option>
        <option>US</option>
        <option>UAE</option>
      </select>
      <button type="submit">Upload Source</button>
    </form>
  );
}
```

---

### Option 4: Web Scraping (Advanced)

**Effort**: 4-6 hours  
**Quality**: Medium (requires cleanup)  
**Best for**: Supplemental sources

```python
# backend/scripts/scrape_sources.py

import httpx
from bs4 import BeautifulSoup

async def scrape_aicpa_guides():
    """Crawl AICPA practice aids"""
    
    base_url = "https://www.aicpa.org/resources/practice-aids"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(base_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for article in soup.find_all("div", class_="resource-card"):
            title = article.find("h3").text.strip()
            link = article.find("a")["href"]
            description = article.find("p").text.strip()
            
            source = Source(
                name=f"AICPA: {title}",
                content=description,
                url=link,
                jurisdiction="US",
                source_type="guidance",
                license_type="public",
                status="Approved"
            )
            
            db.add(source)
    
    db.commit()

# Run scheduled (e.g., weekly):
# python scripts/scrape_sources.py
```

---

### Option 5: Hybrid Approach (Recommended) ✅

**Best strategy**: Start simple, expand gradually

**Phase 1 (Day 1)**: Manual seed
```bash
python scripts/seed_sources.py  # 20 core sources
```

**Phase 2 (Day 2-3)**: API integration
```bash
python scripts/import_fasb.py    # Auto-import from FASB
python scripts/import_ifrs.py    # Auto-import from IFRS
```

**Phase 3 (Day 4-5)**: Admin upload enabled
```
Compliance team uploads custom internal policies
```

**Phase 4 (Week 2)**: Scheduled refresh
```bash
# Background job (runs nightly)
celery beat:
  - scrape_sources (weekly)
  - verify_source_urls (daily)
  - update_embeddings (nightly)
```

---

## Implementation Phases

### Phase 1: Data Layer (Day 1)
```
✅ Create Source SQLAlchemy model
✅ Write Alembic migration for sources table
✅ Manually seed 20-50 core sources
✅ Create indexes on (jurisdiction, source_type, status)
✅ Add Vector column for embeddings
```

**Files to create**:
- `backend/app/domains/source_library/models.py`
- `backend/app/db/migrations/001_create_sources.py`
- `backend/scripts/seed_sources.py`

**Verification**:
```bash
# Check sources in DB
psql -U postgres -d zoikologia -c "SELECT COUNT(*) FROM sources;"
# Output: 50
```

---

### Phase 2: Embedding & Search (Day 2)
```
✅ Install sentence-transformers (or Anthropic embeddings)
✅ Embed all sources: text → vector
✅ Create RAG search endpoint: /api/v1/rag/search
✅ Test semantic search (query → top-5 sources)
```

**Files to create**:
- `backend/app/domains/rag/service.py` (embedding & search logic)
- `backend/app/domains/rag/router.py` (search endpoint)

**Test**:
```bash
curl -X POST http://localhost:8000/api/v1/rag/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "going concern",
    "jurisdiction": "IFRS",
    "limit": 5
  }'

# Returns:
# {
#   "results": [
#     { "source_id": "src-001", "name": "IFRS 1-10", "relevance": 0.95 },
#     { "source_id": "src-002", "name": "FASB ASC 570", "relevance": 0.88 },
#     ...
#   ]
# }
```

---

### Phase 3: Model Gateway (Day 3)
```
✅ Add API credentials (.env):
   - ANTHROPIC_API_KEY
   - OPENAI_API_KEY
   - GOOGLE_API_KEY
✅ Create model_gateway/service.py
✅ Implement /api/v1/models/invoke endpoint
✅ Test LLM integration
```

**Files to create**:
- `backend/app/domains/model_gateway/models.py`
- `backend/app/domains/model_gateway/service.py`
- `backend/app/domains/model_gateway/router.py`

**Test**:
```bash
curl -X POST http://localhost:8000/api/v1/models/invoke \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT" \
  -d '{
    "query": "What is going concern in IFRS?",
    "sources": [
      "Going concern is the assumption...",
      "IFRS 1-10 requires disclosure..."
    ],
    "jurisdiction": "IFRS"
  }'

# Returns:
# {
#   "answer": "Going concern is the assumption that an entity will continue its operations...",
#   "provider": "Claude",
#   "tokens_used": 245
# }
```

---

### Phase 4: Risk Assessment (Day 4)
```
✅ Create risk_safety/models.py
✅ Implement /api/v1/risk/assess endpoint
✅ Define risk patterns (regex + keywords)
✅ Create escalation logic
```

**Files to create**:
- `backend/app/domains/risk_safety/models.py`
- `backend/app/domains/risk_safety/service.py`
- `backend/app/domains/risk_safety/router.py`

**Risk patterns**:
```python
RISK_PATTERNS = {
    "HIGH": [
        r"(audit\s+opinion|auditor\s+responsibility|audit\s+assessment)",
        r"(tax\s+advice|tax\s+treatment|specific.*tax)",
        r"(legal\s+opinion|legal\s+advice|legally\s+binding)"
    ],
    "RESTRICTED": [
        r"(you\s+should.*file|you\s+must.*submit)",
        r"(i\s+recommend\s+you.*file|recommend.*filing)"
    ]
}

def assess_risk(answer: str) -> str:
    """Returns 'Low', 'High', or 'Restricted'"""
    answer_lower = answer.lower()
    
    for pattern in RISK_PATTERNS["RESTRICTED"]:
        if re.search(pattern, answer_lower):
            return "Restricted"
    
    for pattern in RISK_PATTERNS["HIGH"]:
        if re.search(pattern, answer_lower):
            return "High"
    
    return "Low"
```

---

### Phase 5: Full Query Pipeline (Day 5)
```
✅ Create /api/v1/rag/query endpoint
✅ Orchestrate: search → invoke → assess → log
✅ Return formatted response
✅ Test end-to-end
```

**Pipeline code**:
```python
# backend/app/domains/rag/router.py

from fastapi import APIRouter
from app.domains.rag.service import search_sources
from app.domains.model_gateway.service import invoke_model
from app.domains.risk_safety.service import assess_risk
from app.domains.audit_ledger.service import log_decision

@router.post("/api/v1/rag/query")
async def query(
    request: QueryRequest,
    current_user: User = Depends(get_current_user)
):
    """Complete Ask Kriton pipeline"""
    
    # 1. Search sources
    sources = await search_sources(
        query=request.query,
        jurisdiction=request.jurisdiction,
        limit=5
    )
    source_texts = [s.content for s in sources]
    
    # 2. Invoke LLM
    answer = await invoke_model(
        query=request.query,
        sources=source_texts,
        jurisdiction=request.jurisdiction
    )
    
    # 3. Assess risk
    risk_level = assess_risk(answer)
    
    # 4. Create escalation if needed
    escalation_id = None
    if risk_level in ["High", "Restricted"]:
        escalation_id = await create_escalation(
            query=request.query,
            answer=answer,
            risk_level=risk_level,
            user_id=current_user.id
        )
    
    # 5. Log decision
    await log_decision(
        user_id=current_user.id,
        query=request.query,
        answer=answer,
        sources=[s.id for s in sources],
        risk_level=risk_level,
        escalation_id=escalation_id
    )
    
    return {
        "success": True,
        "answer": answer,
        "sources": [
            {
                "id": s.id,
                "name": s.name,
                "text": s.content[:500],
                "url": s.url
            }
            for s in sources
        ],
        "risk_level": risk_level,
        "escalation_id": escalation_id
    }
```

---

### Phase 6: Frontend Integration (Day 5)
```
✅ Create API client: lib/api.ts
✅ Update Ask Kriton page
✅ Remove mock data
✅ Add real API calls
✅ Test end-to-end
```

**Frontend changes**:
```typescript
// frontend/app/ask-kriton/page.tsx

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function AskKritonPage() {
  const [query, setQuery] = useState("");
  const [jurisdiction, setJurisdiction] = useState("IFRS");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);

    try {
      const response = await fetch("/api/v1/rag/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ query, jurisdiction })
      });

      const data = await response.json();
      setResult(data);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={handleSubmit} className="space-y-4">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask Kriton™ about a standard, figure, source or disclosure..."
          className="w-full p-3 border rounded"
          rows={4}
        />
        
        <select
          value={jurisdiction}
          onChange={(e) => setJurisdiction(e.target.value)}
          className="p-2 border rounded"
        >
          <option value="IFRS">IFRS</option>
          <option value="US">US GAAP</option>
          <option value="UAE">UAE</option>
        </select>
        
        <button
          type="submit"
          disabled={loading}
          className="px-4 py-2 bg-blue-600 text-white rounded"
        >
          {loading ? "Thinking..." : "Ask Kriton™"}
        </button>
      </form>

      {result && (
        <div className="space-y-4">
          <div className="bg-white p-4 rounded border">
            <h3 className="font-bold mb-2">Answer</h3>
            <p>{result.answer}</p>
          </div>

          <div className="bg-white p-4 rounded border">
            <h3 className="font-bold mb-2">Sources</h3>
            {result.sources.map((source) => (
              <div key={source.id} className="mb-2 pb-2 border-b">
                <a href={source.url} className="text-blue-600 font-medium">
                  {source.name}
                </a>
                <p className="text-sm text-gray-600">{source.text}...</p>
              </div>
            ))}
          </div>

          <div className="bg-white p-4 rounded border">
            <p>
              Risk Level: <span className={`font-bold ${
                result.risk_level === "Low" ? "text-green-600" :
                result.risk_level === "High" ? "text-orange-600" :
                "text-red-600"
              }`}>{result.risk_level}</span>
            </p>
            {result.escalation_id && (
              <p className="text-orange-600">⚠️ Escalated to expert review</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
```

---

## Quick Start Guide

### Prerequisites
```bash
# Install PostgreSQL + pgvector
brew install postgresql pgvector  # Mac

# Or use Docker
docker run -d \
  -e POSTGRES_PASSWORD=password \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

### Step 1: Setup Database
```bash
cd backend

# Create .env
cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/zoikologia
JWT_SECRET_KEY=dev-secret-key-change-in-prod
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx
EOF

# Install dependencies
pip install -r requirements.txt

# Run migrations
python -m alembic upgrade head

# Seed initial sources
python scripts/seed_sources.py
```

### Step 2: Start Backend
```bash
cd backend
uvicorn app.main:app --reload
```

### Step 3: Test API
```bash
# Test health
curl http://localhost:8000/health
# Output: {"status": "ok"}

# Test search
curl -X POST http://localhost:8000/api/v1/rag/search \
  -H "Content-Type: application/json" \
  -d '{"query": "going concern", "jurisdiction": "IFRS"}'

# Test full pipeline
curl -X POST http://localhost:8000/api/v1/rag/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "query": "What is going concern in IFRS?",
    "jurisdiction": "IFRS"
  }'
```

### Step 4: Wire Frontend
```bash
cd frontend
npm run dev

# Open http://localhost:3000/ask-kriton
# Should now show real backend responses
```

---

## API Endpoints

### Search Endpoint
```
POST /api/v1/rag/search

Request:
{
  "query": "going concern",
  "jurisdiction": "IFRS",
  "limit": 5
}

Response:
{
  "results": [
    {
      "source_id": "src-001",
      "name": "IFRS 1-10",
      "relevance": 0.95,
      "content_preview": "Going concern is..."
    }
  ]
}
```

### Query Endpoint
```
POST /api/v1/rag/query

Request:
{
  "query": "What is going concern in IFRS?",
  "jurisdiction": "IFRS"
}

Response:
{
  "success": true,
  "answer": "Going concern is the assumption that...",
  "sources": [
    {
      "id": "src-001",
      "name": "IFRS 1-10",
      "text": "Full source text...",
      "url": "https://..."
    }
  ],
  "risk_level": "Low",
  "escalation_id": null,
  "timestamp": "2026-07-06T10:30:00Z"
}
```

### Invoke Model Endpoint
```
POST /api/v1/models/invoke

Request:
{
  "query": "What is going concern?",
  "sources": ["Source text 1", "Source text 2"],
  "jurisdiction": "IFRS"
}

Response:
{
  "answer": "Going concern is...",
  "provider": "Claude",
  "tokens_used": 245
}
```

### Risk Assessment Endpoint
```
POST /api/v1/risk/assess

Request:
{
  "query": "Can I audit AI systems?",
  "answer": "Answer text..."
}

Response:
{
  "risk_level": "High",
  "reasons": ["Could imply audit opinion"],
  "escalation_required": true
}
```

---

## Data Summary Table

| Component | Data Type | Source | Frequency | Effort | Status |
|---|---|---|---|---|---|
| **Sources** | Text documents | Manual seed + APIs | On-demand | 1-2 hrs (seed) | ⏳ TODO |
| **Embeddings** | Vectors (384-1536 dims) | sentence-transformers | Per source | Automatic | ⏳ TODO |
| **LLM Credentials** | API keys | Sign up (free tier) | Once | 10 min | ⏳ TODO |
| **Queries** | User questions | Frontend input | Real-time | N/A | ⏳ TODO |
| **Answers** | LLM responses | Claude/GPT API | Per query | API call | ⏳ TODO |
| **Risk Assessment** | Binary/categorical | Pattern matching | Per answer | Automatic | ⏳ TODO |
| **Audit Logs** | Structured records | Auto-logged | Per query | Automatic | ⏳ TODO |

---

## File Structure

```
backend/
├── app/
│   ├── domains/
│   │   ├── source_library/
│   │   │   ├── __init__.py
│   │   │   ├── models.py          ⏳ TODO
│   │   │   ├── schemas.py         ⏳ TODO
│   │   │   └── router.py          ⏳ TODO
│   │   ├── rag/
│   │   │   ├── __init__.py
│   │   │   ├── models.py          ⏳ TODO
│   │   │   ├── schemas.py         ⏳ TODO
│   │   │   ├── service.py         ⏳ TODO (search logic)
│   │   │   └── router.py          ⏳ TODO
│   │   ├── model_gateway/
│   │   │   ├── __init__.py
│   │   │   ├── models.py          ⏳ TODO
│   │   │   ├── service.py         ⏳ TODO (invoke logic)
│   │   │   └── router.py          ⏳ TODO
│   │   ├── risk_safety/
│   │   │   ├── __init__.py
│   │   │   ├── models.py          ⏳ TODO
│   │   │   ├── service.py         ⏳ TODO (assess logic)
│   │   │   └── router.py          ⏳ TODO
│   │   └── audit_ledger/
│   │       ├── __init__.py
│   │       ├── models.py          ⏳ TODO
│   │       ├── service.py         ⏳ TODO (logging)
│   │       └── router.py          ⏳ TODO
│   ├── core/
│   │   └── config.py
│   ├── db/
│   │   ├── base.py
│   │   └── migrations/
│   │       └── 001_create_sources.py   ⏳ TODO
│   └── main.py
├── scripts/
│   ├── seed_sources.py            ⏳ TODO
│   ├── import_fasb.py             ⏳ TODO
│   └── import_ifrs.py             ⏳ TODO
└── tests/
    ├── test_rag_search.py         ⏳ TODO
    ├── test_model_gateway.py      ⏳ TODO
    └── test_risk_assessment.py    ⏳ TODO
```

---

## Success Criteria

✅ **Day 1**: Sources in database, can query them  
✅ **Day 2**: Search returns top-5 relevant sources  
✅ **Day 3**: Claude/GPT integration works  
✅ **Day 4**: Risk assessment detects violations  
✅ **Day 5**: Full pipeline end-to-end  
✅ **Frontend**: Real data (not mock) displayed  

---

## Next Steps

1. [ ] Create Source model + migration
2. [ ] Seed 50 core sources
3. [ ] Implement RAG search endpoint
4. [ ] Add embeddings (pgvector)
5. [ ] Add LLM integration (Claude)
6. [ ] Add risk assessment
7. [ ] Wire frontend to backend
8. [ ] Test end-to-end flow

**Estimated timeline**: 5 working days for MVP
