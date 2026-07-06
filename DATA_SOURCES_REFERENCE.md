# Data Sources Reference

## Quick Lookup Table

### 1. Where Does Each Data Type Come From?

| Data Type | Creation Point | Storage | Auto? | Trigger |
|---|---|---|---|---|
| **Sources** | Admin upload / API import | `sources` table | No | Manual or scheduled job |
| **Embeddings** | Generated from sources | `sources.embedding` (pgvector) | Yes | When source created/updated |
| **Queries** | User submits question | `queries` table | Auto | User clicks Submit |
| **Answers** | LLM generates response | `ai_activities` table | Auto | Query processed |
| **Risk Assessment** | Pattern matching on answer | `ai_activities.risk_level` | Auto | After LLM response |
| **Escalations** | Risk Safety domain detects HIGH | `escalations` table | Auto | High/Restricted risk detected |
| **Audit Log** | Audit Ledger logs decision | `ai_activities` table | Auto | Query completed |

---

## Source Data: 5 Ways to Get It

### 1️⃣ MANUAL SEED (START HERE)

**What**: Add 20-50 sources by hand  
**Time**: 1-2 hours  
**Quality**: ⭐⭐⭐⭐⭐ (Best)  
**Automation**: None  
**Best for**: MVP quick start  

**Steps**:
```python
# backend/scripts/seed_sources.py

from app.db.models import Source
from app.db.base import SessionLocal

sources = [
    {
        "name": "IFRS 1-10 Going Concern",
        "content": "Going concern is the assumption that...",
        "jurisdiction": "IFRS",
        "source_type": "standard",
        "url": "https://www.ifrs.org/..."
    },
    # Add 20+ more...
]

db = SessionLocal()
for s in sources:
    db.add(Source(**s))
db.commit()
```

**Run once**: `python scripts/seed_sources.py`

---

### 2️⃣ API INTEGRATION (OFFICIAL SOURCES)

**What**: Auto-import from FASB, IFRS, AICPA APIs  
**Time**: 2-4 hours to build  
**Quality**: ⭐⭐⭐⭐ (Official, always current)  
**Automation**: Yes (run weekly)  
**Best for**: Long-term maintenance  

**Sources Available**:
- FASB Accounting Standards Codification (~90 topics)
- IFRS Standards (IAS 1-41, IFRS 1-18)
- AICPA Practice Aids
- SEC EDGAR Regulations

**Example**:
```python
# backend/scripts/import_fasb.py

import requests

def import_fasb_asc():
    """Fetch and import all FASB ASC topics"""
    
    base_url = "https://www.fasb.org/..."
    topics = ["205", "210", "220", ...]  # 90 topics
    
    for topic_code in topics:
        response = requests.get(f"{base_url}/{topic_code}")
        
        source = Source(
            name=f"FASB ASC {topic_code}",
            content=extract_text(response),
            jurisdiction="US",
            source_type="standard"
        )
        db.add(source)
    
    db.commit()
```

**Run scheduled**: `celery beat` → weekly

---

### 3️⃣ PDF UPLOAD (USER/ADMIN PROVIDED)

**What**: Admin uploads custom PDFs  
**Time**: 5 min per PDF  
**Quality**: ⭐⭐⭐ (Depends on document)  
**Automation**: No (manual review)  
**Best for**: Company policies, custom guidance  

**How It Works**:
1. Admin clicks "Upload Source"
2. Admin selects PDF file
3. Backend extracts text via pdfplumber
4. Source created with `status="Pending Review"`
5. Admin approves before use
6. Source becomes available for queries

**API**:
```python
# POST /api/v1/sources/upload

@router.post("/api/v1/sources/upload")
async def upload_source(file: UploadFile = File(...)):
    pdf = pdfplumber.open(file.file)
    content = "\n".join(page.extract_text() for page in pdf.pages)
    
    source = Source(
        name=file.filename.replace(".pdf", ""),
        content=content,
        status="Pending Review"
    )
    db.add(source)
    db.commit()
    
    return {"source_id": source.id}
```

---

### 4️⃣ WEB SCRAPING (SUPPLEMENTAL)

**What**: Auto-crawl public websites  
**Time**: 4-6 hours to build  
**Quality**: ⭐⭐ (May need cleanup)  
**Automation**: Yes (run weekly)  
**Best for**: Supplemental content, benchmarking  

**Example**:
```python
# backend/scripts/scrape_aicpa.py

from bs4 import BeautifulSoup
import httpx

async def scrape_aicpa_guides():
    """Crawl AICPA practice aids"""
    
    async with httpx.AsyncClient() as client:
        response = await client.get("https://www.aicpa.org/resources/")
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for card in soup.find_all("div", class_="resource-card"):
            source = Source(
                name=card.find("h3").text,
                url=card.find("a")["href"],
                source_type="guidance"
            )
            db.add(source)
    
    db.commit()
```

**Run scheduled**: `celery beat` → weekly

---

### 5️⃣ DATABASE DUMP (EXISTING DATA)

**What**: Import from existing internal database  
**Time**: 1-3 hours (depends on format)  
**Quality**: ⭐⭐⭐⭐ (Pre-vetted)  
**Automation**: One-time migration  
**Best for**: Companies migrating from legacy system  

**Steps**:
```python
# backend/scripts/migrate_from_legacy.py

import csv

def migrate_legacy_sources():
    """Import from old system export (CSV)"""
    
    with open("legacy_sources.csv") as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            source = Source(
                name=row["title"],
                content=row["body_text"],
                jurisdiction=row["jurisdiction"],
                url=row["source_url"],
                status="Approved"  # Pre-approved
            )
            db.add(source)
    
    db.commit()
```

**Run once**: `python scripts/migrate_from_legacy.py`

---

## LLM & API Costs: Comprehensive Breakdown

### 1. Anthropic (Claude) ✅ RECOMMENDED FOR IFRS

**Pricing Model**: Pay-as-you-go + Free Trial

**Costs**:
- Input tokens: $0.003 per 1K tokens
- Output tokens: $0.015 per 1K tokens
- Example query: ~150 input tokens + 420 output tokens = **$0.0068 per query**
- Monthly estimate (1,000 queries): **$6.80**

**Free Tier**:
- ✅ $5 credit on signup (enough for ~735 queries)
- ✅ No credit card required to start
- ✅ Access to Claude 3.5 Sonnet (best for accounting)

**Sign up**: https://www.anthropic.com/  
**Get API key**: https://console.anthropic.com/account/keys  

**Setup**:
```bash
# Add to .env
ANTHROPIC_API_KEY=sk-ant-xxx

# Verify
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  # Should return valid response (no auth error)
```

**Pros**:
- ✅ Best for IFRS/accounting accuracy
- ✅ Most affordable for production use
- ✅ $5 free credit to test
- ✅ No minimum spend
- ✅ Pay only for what you use

**Cons**:
- ❌ $5 credit expires after 3 months of non-use
- ❌ Need credit card for production

---

### 2. OpenAI (GPT-4) ✅ RECOMMENDED FOR US GAAP

**Pricing Model**: Pay-as-you-go + Free Trial

**Costs**:
- Input tokens: $0.01 per 1K tokens
- Output tokens: $0.03 per 1K tokens
- Example query: ~150 input + 420 output = **$0.0195 per query**
- Monthly estimate (1,000 queries): **$19.50**

**Free Tier**:
- ✅ $5 trial credit on signup
- ✅ Free for 3 months after signup
- ✅ Access to GPT-4, GPT-4 Turbo

**Sign up**: https://platform.openai.com/  
**Get API key**: https://platform.openai.com/account/api-keys  

**Setup**:
```bash
# Add to .env
OPENAI_API_KEY=sk-xxx

# Verify
pip install openai
python -c "import openai; openai.api_key='sk-xxx'; print(openai.Model.list())"
```

**Pros**:
- ✅ Most popular, mature ecosystem
- ✅ $5 free credit
- ✅ Excellent for general accounting
- ✅ Multiple models available

**Cons**:
- ❌ ~2.8x more expensive than Claude
- ❌ 3-month trial limitation
- ❌ After trial, must pay per query

---

### 3. Google (Gemini) (Optional Alternative)

**Pricing Model**: Pay-as-you-go + Free Tier (Forever!)

**Costs**:
- Input tokens: $0.00075 per 1K tokens
- Output tokens: $0.003 per 1K tokens
- Example query: ~150 input + 420 output = **$0.00175 per query**
- Monthly estimate (1,000 queries): **$1.75** (CHEAPEST!)

**Free Tier** (Monthly limits):
- ✅ **60 requests per minute** (free forever!)
- ✅ Up to 10,000 queries/month at no cost
- ✅ No credit card required
- ✅ No expiration

**Sign up**: https://ai.google.dev/  
**Get API key**: https://ai.google.dev/tutorials/setup

**Setup**:
```bash
# Add to .env
GOOGLE_API_KEY=xxx

# Verify
pip install google-generativeai
python -c "import google.generativeai as genai; genai.configure(api_key='xxx'); print(genai.list_models())"
```

**Pros**:
- ✅ CHEAPEST option ($0.00175 per query)
- ✅ Free tier forever (no expiration!)
- ✅ 10,000 free queries/month
- ✅ No credit card needed for free tier
- ✅ Best for testing and MVP

**Cons**:
- ❌ May be less accurate for accounting (not trained specifically)
- ❌ Rate limited on free tier
- ❌ Newer API (less mature)  

---

## Database Setup

### PostgreSQL with pgvector

**Installation**:
```bash
# macOS
brew install postgresql@16 pgvector

# Ubuntu
sudo apt-get install postgresql-16 postgresql-16-pgvector

# Docker (recommended)
docker run -d \
  -e POSTGRES_PASSWORD=password \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

**Create database**:
```bash
psql -U postgres

# In psql:
CREATE DATABASE zoikologia;
CREATE EXTENSION vector;
\q
```

**Connection string**:
```env
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/zoikologia
```

---

## Embedding Models

### Option A: Sentence Transformers (FREE)

```python
from sentence_transformers import SentenceTransformer

# Download model once (50MB)
model = SentenceTransformer('all-MiniLM-L6-v2')

# Embed text
embedding = model.encode("Going concern is...")
# Returns: array of 384 floats

# Store in pgvector
source.embedding = embedding
db.add(source)
db.commit()
```

**Cost**: Free (local)  
**Speed**: ~10ms per embedding  
**Dimensions**: 384  
**Quality**: Good for general use  

---

### Option B: Anthropic Embeddings

```python
import anthropic

client = anthropic.Anthropic(api_key="sk-ant-xxx")

embedding = client.beta.embeddings.embed(
    model="claude-3-5-embed",
    input="Going concern is...",
).embeddings[0].embedding

# Returns: array of 1024 floats
```

**Cost**: $0.02 per 1M tokens  
**Speed**: ~200ms per embedding (API)  
**Dimensions**: 1024  
**Quality**: ⭐⭐⭐⭐⭐ (Best)  

---

### Option C: OpenAI Embeddings

```python
import openai

embedding = openai.Embedding.create(
    model="text-embedding-3-small",
    input="Going concern is..."
).data[0].embedding

# Returns: array of 1536 floats
```

**Cost**: $0.02 per 1M tokens  
**Speed**: ~200ms (API)  
**Dimensions**: 1536  
**Quality**: ⭐⭐⭐⭐⭐ (Industry standard)  

---

## Implementation Timeline

### Week 1: Core Ask Kriton MVP

| Day | Task | Effort | Status |
|---|---|---|---|
| **Mon** | Seed 50 sources + DB setup | 2 hrs | ⏳ TODO |
| **Tue** | RAG search endpoint | 4 hrs | ⏳ TODO |
| **Wed** | Embeddings (pgvector) | 3 hrs | ⏳ TODO |
| **Thu** | LLM integration (Claude) | 3 hrs | ⏳ TODO |
| **Fri** | Risk + Audit logging + Frontend | 5 hrs | ⏳ TODO |
| | **Total** | **17 hours** | |

### Week 2: Enhancements

| Task | Effort | Impact |
|---|---|---|
| API integration (FASB/IFRS) | 4 hrs | +200 sources |
| PDF upload interface | 3 hrs | User-friendly |
| Background job (scheduled refresh) | 2 hrs | Auto-update sources |
| Advanced risk patterns | 2 hrs | Better detection |
| **Total** | **11 hours** | |

---

## Data Flow Diagram

```
USER QUERY
    │
    ├─→ "What is going concern in IFRS?"
    ├─→ Jurisdiction: "IFRS"
    └─→ User: "auditor@company.com"
    
    ↓ POST /api/v1/rag/query
    
┌─────────────────────────────────────┐
│   SOURCES (database)                │
│   ├─ IFRS 1-10 ✓                   │
│   ├─ FASB ASC 570 ✓                │
│   ├─ AICPA guidance ✓              │
│   └─ (50+ more sources)            │
└─────────┬───────────────────────────┘
          │
          ├─→ Search: "going concern" + "IFRS"
          ├─→ Convert to vector: [0.2, 0.5, ...]
          ├─→ cosine_similarity() vs all sources
          └─→ Top-5 results
          
          ↓
    ┌───────────────────────────┐
    │ LLM (Claude API)          │
    │ ├─ Query + Sources        │
    │ └─ Generate Answer        │
    └──────────┬────────────────┘
               │
               └─→ "Going concern is..."
               
               ↓
    ┌───────────────────────────┐
    │ Risk Assessment           │
    │ ├─ Check for "audit op.." │
    │ ├─ Check for "tax adv.."  │
    │ └─ risk_level = "Low"     │
    └──────────┬────────────────┘
               │
               └─→ If HIGH → Create escalation
               
               ↓
    ┌───────────────────────────┐
    │ Audit Log                 │
    │ INSERT INTO ai_activities │
    │ (query, answer, sources,  │
    │  risk_level, timestamp)   │
    └──────────┬────────────────┘
               │
               ↓
    RESPONSE TO USER
    ├─ Answer ✓
    ├─ Sources ✓
    ├─ Risk Level ✓
    ├─ Escalation (if needed) ✓
    └─ Audit Trail Link ✓
```

---

## Checklist: Ready to Start?

- [ ] PostgreSQL running locally (or Docker)
- [ ] pgvector extension installed
- [ ] `zoikologia` database created
- [ ] Backend Python environment set up
- [ ] API credentials (Claude/GPT) obtained
- [ ] `.env` file with credentials
- [ ] 20+ source documents ready to seed
- [ ] Source model/migration files created
- [ ] Alembic migration run (`upgrade head`)
- [ ] Initial seeds imported
- [ ] RAG search endpoint working
- [ ] Embeddings generating
- [ ] LLM integration tested
- [ ] Risk assessment rules defined
- [ ] Audit logging implemented
- [ ] Frontend integrated with backend
- [ ] End-to-end test successful

---

## Troubleshooting

### "ModuleNotFoundError: pgvector"
```bash
pip install pgvector sqlalchemy[asyncio]
```

### "Connection refused to localhost:5432"
```bash
# Check PostgreSQL is running
brew services list  # macOS
systemctl status postgresql  # Linux
docker ps  # Docker
```

### "ANTHROPIC_API_KEY not found"
```bash
# Make sure .env file exists in backend/ directory
cat .env | grep ANTHROPIC
# Should output: ANTHROPIC_API_KEY=sk-ant-xxx
```

### "Vector dimension mismatch"
```
Error: dimension mismatch - 384 vs 1536

Solution: Use consistent embedding model
- If using sentence-transformers: all 384
- If using OpenAI: all 1536
```

---

## Recommended Reading

- [Retrieval Augmented Generation (RAG)](https://en.wikipedia.org/wiki/Prompt_engineering#Retrieval-augmented_generation)
- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [Anthropic API Guide](https://docs.anthropic.com/)
- [Sentence Transformers Guide](https://www.sbert.net/)

---

**Status**: 📋 Ready to implement  
**Last updated**: 2026-07-06  
**Next milestone**: Day 1 — Seed sources + DB setup
