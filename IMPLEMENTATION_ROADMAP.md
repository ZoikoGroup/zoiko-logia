# Ask Kriton Implementation Roadmap

## Phase Overview

```
WEEK 1 (MVP)
├─ Day 1: Data Layer (Sources + Database)
├─ Day 2: RAG Search (Retrieval)
├─ Day 3: Model Gateway (LLM Integration)
├─ Day 4: Risk Assessment
└─ Day 5: Frontend Integration

WEEK 2 (Enhancements)
├─ API Integration (FASB/IFRS imports)
├─ PDF Upload Interface
├─ Background Jobs (Scheduled refresh)
└─ Advanced Risk Patterns

WEEK 3+ (Full System)
├─ Other 15 domains
├─ Overview Dashboard connected
├─ Admin Governance features
└─ Full deployment
```

---

## WEEK 1: MVP SPRINT

### DAY 1: Data Layer & Database Setup

**Morning (2 hours)**

- [ ] **PostgreSQL Setup**
  - [ ] Install PostgreSQL 16 (brew / docker)
  - [ ] Install pgvector extension
  - [ ] Create `zoikologia` database
  - [ ] Create `.env` with DATABASE_URL

- [ ] **Alembic Migration**
  - [ ] Initialize alembic: `alembic init app/db/migrations`
  - [ ] Create `001_create_sources.py` migration

**Afternoon (2 hours)**

- [ ] **Source Model**
  - [ ] Create `backend/app/domains/source_library/models.py`
  - [ ] Define Source class with all fields (see guide)
  - [ ] Add Vector column for embeddings
  - [ ] Add indexes on `jurisdiction`, `source_type`, `status`

- [ ] **Database Migration**
  - [ ] Run `alembic upgrade head`
  - [ ] Verify table created: `psql -d zoikologia -c "\dt sources"`

**Evening (1 hour)**

- [ ] **Seed Initial Sources**
  - [ ] Create `backend/scripts/seed_sources.py`
  - [ ] Add 50 core accounting sources manually
  - [ ] Run: `python scripts/seed_sources.py`
  - [ ] Verify: `psql -d zoikologia -c "SELECT COUNT(*) FROM sources;"`
  - [ ] Expected: 50 rows

**Deliverable**: ✅ 50 sources in database

---

### DAY 2: RAG Search (Retrieval)

**Morning (2 hours)**

- [ ] **Embedding Setup**
  - [ ] Install sentence-transformers: `pip install sentence-transformers`
  - [ ] Create embedding function in `service.py`
  - [ ] Download model: `SentenceTransformer('all-MiniLM-L6-v2')`

- [ ] **Embed All Sources**
  - [ ] Create `backend/scripts/embed_sources.py`
  - [ ] Batch process all 50 sources
  - [ ] Generate embeddings: text → 384-dim vector
  - [ ] Store in `sources.embedding` column
  - [ ] Run: `python scripts/embed_sources.py`

**Afternoon (2 hours)**

- [ ] **RAG Search Service**
  - [ ] Create `backend/app/domains/rag/models.py`
  - [ ] Create `backend/app/domains/rag/schemas.py` (Pydantic)
  - [ ] Create `backend/app/domains/rag/service.py`
  - [ ] Implement `search_sources()` function:
    - Convert query to vector
    - Cosine similarity search in pgvector
    - Return top-5 with relevance scores

- [ ] **RAG Search Endpoint**
  - [ ] Create `backend/app/domains/rag/router.py`
  - [ ] `POST /api/v1/rag/search` endpoint
  - [ ] Input: `{ query, jurisdiction, limit }`
  - [ ] Output: `{ results: [ { source_id, name, relevance } ] }`

**Evening (1 hour)**

- [ ] **Test RAG Search**
  - [ ] Start backend: `uvicorn app.main:app --reload`
  - [ ] Test endpoint:
    ```bash
    curl -X POST http://localhost:8000/api/v1/rag/search \
      -H "Content-Type: application/json" \
      -d '{"query": "going concern", "jurisdiction": "IFRS", "limit": 5}'
    ```
  - [ ] Verify: Returns top-5 sources with scores

**Deliverable**: ✅ Search endpoint returns relevant sources

---

### DAY 3: Model Gateway (LLM Integration)

**Morning (2 hours)**

- [ ] **Prepare API Keys**
  - [ ] Sign up for Anthropic: https://www.anthropic.com/
  - [ ] Get API key from console
  - [ ] Add to `.env`: `ANTHROPIC_API_KEY=sk-ant-xxx`
  - [ ] Verify access:
    ```bash
    python -c "import anthropic; client = anthropic.Anthropic(); print('✓ Connected')"
    ```

- [ ] **Model Gateway Service**
  - [ ] Create `backend/app/domains/model_gateway/models.py`
  - [ ] Create `backend/app/domains/model_gateway/service.py`
  - [ ] Implement `invoke_model()` function:
    - Accept: query, sources, jurisdiction
    - Route: IFRS → Claude, US → GPT (policy)
    - Call LLM API with sources in context
    - Return generated answer

**Afternoon (2 hours)**

- [ ] **Model Gateway Endpoint**
  - [ ] Create `backend/app/domains/model_gateway/router.py`
  - [ ] `POST /api/v1/models/invoke` endpoint
  - [ ] Input: `{ query, sources, jurisdiction }`
  - [ ] Output: `{ answer, provider, tokens_used }`

- [ ] **Test LLM Integration**
  - [ ] Test endpoint:
    ```bash
    curl -X POST http://localhost:8000/api/v1/models/invoke \
      -H "Content-Type: application/json" \
      -d '{
        "query": "What is going concern?",
        "sources": ["Going concern is...", "IFRS 1-10 requires..."],
        "jurisdiction": "IFRS"
      }'
    ```
  - [ ] Verify: Returns Claude-generated answer

**Evening (1 hour)**

- [ ] **Cost & Rate Limiting**
  - [ ] Document expected costs (~$0.003 per query)
  - [ ] Consider adding rate limiting (not required for MVP)
  - [ ] Test with 5-10 queries to verify API is working

**Deliverable**: ✅ LLM generates answers with sources

---

### DAY 4: Risk Assessment & Escalation

**Morning (2 hours)**

- [ ] **Risk Safety Model & Service**
  - [ ] Create `backend/app/domains/risk_safety/models.py`
  - [ ] Define Escalation model
  - [ ] Create `backend/app/domains/risk_safety/service.py`
  - [ ] Implement `assess_risk()` function:
    - Regex patterns for HIGH risk: "audit opinion", "tax advice"
    - Regex patterns for RESTRICTED: "you should file", "I recommend filing"
    - Return: "Low" / "High" / "Restricted"

- [ ] **Risk Assessment Endpoint**
  - [ ] Create `backend/app/domains/risk_safety/router.py`
  - [ ] `POST /api/v1/risk/assess` endpoint
  - [ ] Input: `{ query, answer }`
  - [ ] Output: `{ risk_level, reasons, escalation_required }`

**Afternoon (2 hours)**

- [ ] **Audit Ledger Model & Logging**
  - [ ] Create `backend/app/domains/audit_ledger/models.py`
  - [ ] Define AIActivity model (query log)
  - [ ] Define Escalation model
  - [ ] Create `backend/app/domains/audit_ledger/service.py`
  - [ ] Implement `log_decision()` function:
    - Record query, sources, answer, risk level
    - Create escalation if needed
    - Store all metadata

- [ ] **Test Risk Assessment**
  - [ ] Test with safe query: "What is materiality?"
    - Expected: risk_level = "Low"
  - [ ] Test with high-risk query: "Can I audit AI systems?"
    - Expected: risk_level = "High", escalation_required = true

**Evening (1 hour)**

- [ ] **Escalation Database Check**
  - [ ] Verify escalations created:
    ```sql
    SELECT * FROM escalations WHERE created_at > NOW() - INTERVAL '1 hour';
    ```
  - [ ] Verify audit activities logged:
    ```sql
    SELECT * FROM ai_activities ORDER BY created_at DESC LIMIT 10;
    ```

**Deliverable**: ✅ Risk detection + escalation creation working

---

### DAY 5: Full Pipeline + Frontend Integration

**Morning (2 hours)**

- [ ] **Complete RAG Query Endpoint**
  - [ ] Create `backend/app/domains/rag/router.py` (if not done)
  - [ ] `POST /api/v1/rag/query` endpoint
  - [ ] Orchestrate full pipeline:
    1. Search sources
    2. Invoke LLM
    3. Assess risk
    4. Create escalation (if needed)
    5. Log decision
    6. Return formatted response
  - [ ] Input: `{ query, jurisdiction, user_id }`
  - [ ] Output: `{ success, answer, sources[], risk_level, escalation_id }`

- [ ] **End-to-End Backend Test**
  - [ ] Test full pipeline:
    ```bash
    curl -X POST http://localhost:8000/api/v1/rag/query \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $JWT" \
      -d '{
        "query": "What is going concern in IFRS?",
        "jurisdiction": "IFRS"
      }'
    ```
  - [ ] Expected response: answer + sources + risk + audit trail

**Afternoon (2 hours)**

- [ ] **Frontend Integration**
  - [ ] Create `frontend/lib/api.ts` with fetch functions:
    - `queryKriton(query, jurisdiction)`
    - `searchSources(query)`
  - [ ] Update `frontend/app/ask-kriton/page.tsx`:
    - Remove mock data imports
    - Add useState for query, jurisdiction, result, loading
    - Add useEffect for API calls
    - Replace hardcoded answer with real API response
    - Display sources with links
    - Show risk level indicator

- [ ] **Test Frontend-Backend Connection**
  - [ ] Start backend: `cd backend && uvicorn app.main:app --reload`
  - [ ] Start frontend: `cd frontend && npm run dev`
  - [ ] Open http://localhost:3000/ask-kriton
  - [ ] Enter query: "What is going concern in IFRS?"
  - [ ] Submit and verify real answer appears

**Evening (1 hour)**

- [ ] **End-to-End Validation**
  - [ ] ✅ Query submitted from frontend
  - [ ] ✅ Sources retrieved (top-5 relevant)
  - [ ] ✅ Claude generates answer
  - [ ] ✅ Risk assessment runs
  - [ ] ✅ Audit logged
  - [ ] ✅ Response returned to frontend
  - [ ] ✅ Frontend displays answer + sources
  - [ ] Repeat 3-5 times with different queries

**Deliverable**: ✅ Ask Kriton fully functional (MVP complete!)

---

## WEEK 1 Completion Checklist

**Database & Infrastructure**
- [ ] PostgreSQL running with pgvector
- [ ] `zoikologia` database created
- [ ] 50 sources seeded
- [ ] Embeddings generated for all sources

**Backend (5 domains)**
- [ ] Source Library domain created
- [ ] RAG domain with search endpoint
- [ ] Model Gateway with LLM integration
- [ ] Risk Safety with escalation logic
- [ ] Audit Ledger with logging

**Frontend**
- [ ] Ask Kriton page connected to backend
- [ ] Mock data removed
- [ ] Real answers displayed
- [ ] Sources shown with citations
- [ ] Risk level shown

**Testing**
- [ ] Each endpoint tested individually
- [ ] Full end-to-end flow tested
- [ ] 10+ queries executed successfully
- [ ] Escalations created for high-risk queries
- [ ] Audit logs verified

**Documentation**
- [ ] KRITON_DEVELOPMENT_GUIDE.md ✅
- [ ] DATA_SOURCES_REFERENCE.md ✅
- [ ] This roadmap ✅

---

## WEEK 2: Enhancements

### Task 1: API Integration (FASB/IFRS)
- [ ] Create `scripts/import_fasb.py`
- [ ] Create `scripts/import_ifrs.py`
- [ ] Fetch and import 100+ official standards
- [ ] Schedule as background job

### Task 2: PDF Upload Interface
- [ ] Create upload endpoint: `POST /api/v1/sources/upload`
- [ ] Frontend: Upload form in Source Library
- [ ] Admin approval workflow
- [ ] Auto-extract text from PDFs

### Task 3: Background Jobs
- [ ] Set up Celery + Redis
- [ ] Create refresh job (daily source updates)
- [ ] Create archive job (old audit logs)
- [ ] Schedule via celery beat

### Task 4: Advanced Patterns
- [ ] Add domain-specific risk rules
- [ ] Add jurisdiction-specific escalation rules
- [ ] Add custom response templates
- [ ] Add response quality metrics

---

## Quick Start (Copy-Paste Commands)

### Setup (Run once)
```bash
# Backend setup
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt

# Create .env
cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/zoikologia
JWT_SECRET_KEY=dev-secret-key
ANTHROPIC_API_KEY=sk-ant-xxx
EOF

# Database setup
python -m alembic upgrade head
python scripts/seed_sources.py
python scripts/embed_sources.py

# Start backend
uvicorn app.main:app --reload
```

### Frontend (Run in parallel)
```bash
cd frontend
npm run dev

# Open http://localhost:3000/ask-kriton
```

### Daily Development
```bash
# Terminal 1: Backend
cd backend && uvicorn app.main:app --reload

# Terminal 2: Frontend
cd frontend && npm run dev

# Test in browser
# http://localhost:3000/ask-kriton
```

---

## Day-by-Day Progress Tracking

### Day 1 Completion
```
TARGET: 50 sources in database, running locally
VERIFICATION:
psql -d zoikologia -c "SELECT COUNT(*) FROM sources;"
# Output: 50

🟢 COMPLETE when:
  - [ ] Database tables created
  - [ ] 50 sources inserted
  - [ ] Backend running (no errors)
```

### Day 2 Completion
```
TARGET: Search endpoint returns top-5 sources
VERIFICATION:
curl -X POST http://localhost:8000/api/v1/rag/search \
  -H "Content-Type: application/json" \
  -d '{"query": "materiality", "jurisdiction": "IFRS", "limit": 5}'

🟢 COMPLETE when:
  - [ ] Returns 5 sources
  - [ ] Results ranked by relevance (0.0-1.0)
  - [ ] Response time < 500ms
```

### Day 3 Completion
```
TARGET: LLM generates answers
VERIFICATION:
curl -X POST http://localhost:8000/api/v1/models/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is materiality?",
    "sources": ["Source 1", "Source 2"],
    "jurisdiction": "IFRS"
  }'

🟢 COMPLETE when:
  - [ ] Returns Claude answer
  - [ ] Includes source references
  - [ ] Response time < 3 seconds
```

### Day 4 Completion
```
TARGET: Risk detection + escalations
VERIFICATION:
curl -X POST http://localhost:8000/api/v1/risk/assess \
  -H "Content-Type: application/json" \
  -d '{"query": "Can you audit AI?", "answer": "..."}'

🟢 COMPLETE when:
  - [ ] Returns risk_level: "Low" / "High" / "Restricted"
  - [ ] Escalations table has entries
  - [ ] Risk patterns working
```

### Day 5 Completion
```
TARGET: Frontend displays real answers
VERIFICATION:
1. Open http://localhost:3000/ask-kriton
2. Type: "What is going concern?"
3. Click "Ask Kriton™"
4. Observe real answer + sources

🟢 COMPLETE when:
  - [ ] Answer displays (not mock)
  - [ ] Sources shown with links
  - [ ] Risk level shown
  - [ ] Response time < 5 seconds
  - [ ] No console errors
```

---

## Troubleshooting by Day

### Day 1: Database Issues
```
ERROR: psycopg2.OperationalError: connection refused
SOLUTION:
  - Check PostgreSQL running: brew services list
  - Check pgvector installed: psql -c "CREATE EXTENSION vector"
  - Verify DATABASE_URL in .env

ERROR: no relation "sources" exists
SOLUTION:
  - Run migrations: python -m alembic upgrade head
  - Verify: psql -d zoikologia -c "\dt"
```

### Day 2: Embedding Issues
```
ERROR: dimension mismatch in pgvector
SOLUTION:
  - Verify all embeddings are same dimension (384 for all-MiniLM)
  - Clear embeddings and re-generate: python scripts/embed_sources.py

ERROR: ModuleNotFoundError: sentence_transformers
SOLUTION:
  - pip install sentence-transformers
  - First run downloads model (~50MB)
```

### Day 3: LLM Issues
```
ERROR: 401 Unauthorized (Claude API)
SOLUTION:
  - Check ANTHROPIC_API_KEY in .env
  - Verify API key at https://console.anthropic.com/account/keys
  - Test: python -c "import anthropic; ..."

ERROR: Rate limited
SOLUTION:
  - Add delays between requests
  - Use smaller batches for testing
```

### Day 4: Risk Assessment Issues
```
ERROR: Escalations not created
SOLUTION:
  - Check risk patterns match your query
  - Verify escalations table created
  - Test manually: python -c "from app.domains.risk_safety.service import assess_risk; ..."

ERROR: Regex not matching
SOLUTION:
  - Test patterns: python -c "import re; re.search(pattern, text)"
  - Make patterns case-insensitive: re.search(r'audit', text, re.IGNORECASE)
```

### Day 5: Frontend Issues
```
ERROR: CORS error on API calls
SOLUTION:
  - Ensure backend has CORS middleware
  - Check credentials: 'include' in fetch options
  - Verify API URL: http://localhost:8000 (not 3000)

ERROR: "Cannot find module api.ts"
SOLUTION:
  - Verify file created: ls frontend/lib/api.ts
  - Check import path: import { queryKriton } from '@/lib/api'

ERROR: Always shows loading spinner
SOLUTION:
  - Check browser console for errors
  - Check backend logs (stderr)
  - Verify JWT token is valid
```

---

## Success Metrics

**By end of Week 1, MVP is complete if:**
- ✅ 5+ queries executed end-to-end
- ✅ All answers trace to sources
- ✅ Risk detection working (5+ escalations created)
- ✅ Audit logs complete (query → answer → logs)
- ✅ Frontend shows real data (not mock)
- ✅ No critical errors in logs
- ✅ Response time acceptable (<5s)

**By end of Week 2, Production-ready if:**
- ✅ 200+ sources in database
- ✅ Multiple LLM providers available
- ✅ Background jobs running
- ✅ PDF upload working
- ✅ Admin approval workflow implemented
- ✅ All 5 core domains complete

---

## Notes for Implementation Team

1. **Start with manual seeds** (Day 1) — Fastest way to validate pipeline
2. **Don't perfectionize Day 1-3** — Move fast, iterate
3. **Test each layer independently** before combining
4. **Keep API keys secure** — Never commit .env to git
5. **Use mock LLM responses for testing** if API costs concern you
6. **Save .curl commands** for repeated testing
7. **Document any issues** found — helps Week 2 planning

---

## Questions to Ask Yourself Daily

- [ ] **Day 1**: Can I run a SELECT query and see 50 sources?
- [ ] **Day 2**: Can I search and get back top-5 relevant sources?
- [ ] **Day 3**: Can I get a Claude-generated answer?
- [ ] **Day 4**: Can I detect high-risk queries and create escalations?
- [ ] **Day 5**: Can I enter a question in the UI and see a real answer?

If all answers are YES → MVP complete! 🎉

---

**Status**: 📋 Ready to implement  
**Estimated Effort**: 40 hours (5 days, 8 hrs/day)  
**Team Size**: 1-2 senior engineers  
**Start Date**: [WHEN YOU'RE READY]
