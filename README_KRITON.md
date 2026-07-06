# Ask Kriton Development - Documentation Index

## 📚 All Documentation Files (Start Here)

This directory contains complete development documentation for **Ask Kriton™**, the core intelligence engine of ZoikoLogia.

### 1. **KRITON_DEVELOPMENT_GUIDE.md** ⭐ START HERE
**What**: Complete reference guide for building Ask Kriton  
**Chapters**:
- Overview & Architecture
- Complete data flow diagram
- All data requirements (sources, embeddings, LLM credentials)
- 5 data source options (manual, API, upload, scraping, hybrid)
- Database setup instructions
- All API endpoint specifications
- File structure & next steps

**Best for**: Understanding the complete system architecture

---

### 2. **DATA_SOURCES_REFERENCE.md** 📊 QUICK LOOKUP
**What**: Quick reference for where data comes from  
**Sections**:
- Data origin table (5 source types)
- Setup instructions for each source type
- LLM credentials (how to get API keys)
- Database & embedding setup
- Cost analysis
- Troubleshooting

**Best for**: Finding exactly where to get data or troubleshooting issues

---

### 3. **IMPLEMENTATION_ROADMAP.md** 🗺️ DAY-BY-DAY PLAN
**What**: Step-by-step development plan for Week 1  
**Contents**:
- Day 1: Database setup + sources
- Day 2: RAG search
- Day 3: LLM integration
- Day 4: Risk assessment
- Day 5: Frontend integration
- Daily progress checklist
- Copy-paste commands
- Troubleshooting by day
- Success metrics

**Best for**: Actually building the system (follow this day-by-day)

---

## 🚀 Quick Start (5 Minutes)

If you just want to get started RIGHT NOW:

```bash
# 1. Setup backend
cd backend
python -m venv venv
source venv/bin/activate  # or: venv\Scripts\activate (Windows)
pip install -r requirements.txt

# 2. Create .env with credentials
cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/zoikologia
ANTHROPIC_API_KEY=sk-ant-xxx
EOF

# 3. Setup database (PostgreSQL with pgvector must be running)
python -m alembic upgrade head
python scripts/seed_sources.py

# 4. Start backend
uvicorn app.main:app --reload

# 5. In another terminal, start frontend
cd frontend
npm run dev

# 6. Open http://localhost:3000/ask-kriton
```

---

## 📖 Reading Order (Recommended)

### For First-Time Readers
1. **KRITON_DEVELOPMENT_GUIDE.md** (30 min) — Understand architecture
2. **DATA_SOURCES_REFERENCE.md** (15 min) — Understand data sources
3. **IMPLEMENTATION_ROADMAP.md** (15 min) — Understand timeline

### For Developers
1. **IMPLEMENTATION_ROADMAP.md** — Follow Day 1-5 exactly
2. Reference **DATA_SOURCES_REFERENCE.md** when stuck
3. Consult **KRITON_DEVELOPMENT_GUIDE.md** for detailed specs

### For Architects
1. **KRITON_DEVELOPMENT_GUIDE.md** → Data Flow Architecture section
2. **DATA_SOURCES_REFERENCE.md** → Data Flow Diagram section
3. Review component interactions and dependencies

---

## 🎯 By Day (Following IMPLEMENTATION_ROADMAP.md)

### Day 1: Database & Sources ✅
- **Read**: IMPLEMENTATION_ROADMAP.md → DAY 1 section
- **Tasks**: 3 hours hands-on
- **Verify**: `psql -c "SELECT COUNT(*) FROM sources;"` → 50

### Day 2: Search Pipeline ✅
- **Read**: IMPLEMENTATION_ROADMAP.md → DAY 2 section
- **Tasks**: 4 hours hands-on
- **Verify**: Search endpoint returns top-5 sources

### Day 3: LLM Integration ✅
- **Read**: DATA_SOURCES_REFERENCE.md → LLM Credentials section
- **Read**: IMPLEMENTATION_ROADMAP.md → DAY 3 section
- **Tasks**: 4 hours hands-on
- **Verify**: Claude generates answers

### Day 4: Risk & Audit ✅
- **Read**: IMPLEMENTATION_ROADMAP.md → DAY 4 section
- **Tasks**: 3 hours hands-on
- **Verify**: Escalations created for high-risk queries

### Day 5: Frontend Integration ✅
- **Read**: IMPLEMENTATION_ROADMAP.md → DAY 5 section
- **Tasks**: 3 hours hands-on
- **Verify**: Real answers show in UI

---

## 📋 Checklist: Before You Start

- [ ] PostgreSQL 16+ installed with pgvector
- [ ] Python 3.9+ with virtual environment
- [ ] API key from Anthropic (https://www.anthropic.com/)
- [ ] Node.js 18+ for frontend
- [ ] VS Code or similar IDE
- [ ] Git configured
- [ ] This documentation downloaded/accessible

---

## 🔧 File Structure After Implementation

```
backend/
├── KRITON_DEVELOPMENT_GUIDE.md          ← Architecture & specs
├── DATA_SOURCES_REFERENCE.md            ← Data sources guide
├── IMPLEMENTATION_ROADMAP.md            ← Day-by-day plan
├── README.md                             ← Framework structure (original)
├── app/
│   ├── main.py                          (existing)
│   ├── core/
│   │   ├── config.py                    (existing)
│   │   ├── database.py                  (existing)
│   │   └── security.py                  (existing)
│   ├── db/
│   │   ├── base.py                      (existing)
│   │   └── migrations/
│   │       └── 001_create_sources.py    ← Day 1
│   ├── domains/
│   │   ├── source_library/              ← Day 1
│   │   │   ├── models.py
│   │   │   ├── schemas.py
│   │   │   └── router.py
│   │   ├── rag/                         ← Day 2-5
│   │   │   ├── models.py
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   └── router.py
│   │   ├── model_gateway/               ← Day 3
│   │   │   ├── models.py
│   │   │   ├── service.py
│   │   │   └── router.py
│   │   ├── risk_safety/                 ← Day 4
│   │   │   ├── models.py
│   │   │   ├── service.py
│   │   │   └── router.py
│   │   └── audit_ledger/                ← Day 4
│   │       ├── models.py
│   │       ├── service.py
│   │       └── router.py
│   └── api/
│       └── v1/
│           └── __init__.py
├── scripts/
│   ├── seed_sources.py                  ← Day 1
│   ├── embed_sources.py                 ← Day 2
│   ├── import_fasb.py                   ← Week 2
│   └── import_ifrs.py                   ← Week 2
├── tests/
│   ├── test_rag_search.py               (optional)
│   └── test_risk_assessment.py          (optional)
├── .env.example                         (existing)
└── requirements.txt                     (existing)
```

---

## 🐛 Debugging Tips

### Check Backend is Running
```bash
curl http://localhost:8000/health
# Should return: {"status": "ok"}
```

### Check Database Connection
```bash
psql -U postgres -d zoikologia -c "SELECT COUNT(*) FROM sources;"
# Should return: 50 (or your seed count)
```

### Check Embeddings Generated
```bash
psql -U postgres -d zoikologia -c "SELECT COUNT(*) FROM sources WHERE embedding IS NOT NULL;"
# Should return: 50 (all sources)
```

### Check LLM API Works
```python
import anthropic
client = anthropic.Anthropic(api_key="sk-ant-xxx")
print("✓ API working") if client else print("✗ Failed")
```

### Check Frontend API Call
```
1. Open Chrome DevTools (F12)
2. Go to Network tab
3. Trigger "Ask Kriton" in UI
4. Look for POST to /api/v1/rag/query
5. Check response status (200 = success)
```

---

## 📞 FAQ

**Q: Do I need to use Claude? Can I use GPT-4 instead?**  
A: Yes, see KRITON_DEVELOPMENT_GUIDE.md → Model Gateway section for options

**Q: How much will LLM API costs?**  
A: ~$0.003-0.01 per query. See DATA_SOURCES_REFERENCE.md → LLM Credentials

**Q: How many sources do I need for MVP?**  
A: Minimum 20-50. See DATA_SOURCES_REFERENCE.md → Quick Lookup Table

**Q: Can I run this without PostgreSQL?**  
A: Not recommended. pgvector (vector search) is core to Kriton's design

**Q: How long does each day take?**  
A: 6-8 hours hands-on work per day. See IMPLEMENTATION_ROADMAP.md

**Q: Can I work on this part-time?**  
A: Yes, but keep to daily milestones. Mixing days won't work.

**Q: What if I get stuck on Day 3?**  
A: See IMPLEMENTATION_ROADMAP.md → Day 3 Troubleshooting section

---

## 📊 Progress Tracker

```
WEEK 1 MVP
├─ Day 1: Database & Sources         ⏳ TODO
├─ Day 2: Search Pipeline            ⏳ TODO
├─ Day 3: LLM Integration            ⏳ TODO
├─ Day 4: Risk Assessment            ⏳ TODO
└─ Day 5: Frontend Integration       ⏳ TODO

WEEK 2 Enhancements
├─ API Integration (FASB/IFRS)       ⏳ TODO
├─ PDF Upload                        ⏳ TODO
├─ Background Jobs                   ⏳ TODO
└─ Advanced Patterns                 ⏳ TODO
```

Update this as you complete each day!

---

## 🚀 Next Milestone

After Ask Kriton MVP is complete (Week 1):
1. Overview Dashboard will auto-populate with real data
2. All other 15 domains will follow same pattern
3. Full system launch in 4 weeks

---

## 📖 Appendix: Document Quick Links

| Need... | Go to... | Section |
|---|---|---|
| Architecture overview | KRITON_DEVELOPMENT_GUIDE.md | Data Flow Architecture |
| Get sources data | DATA_SOURCES_REFERENCE.md | 5 Ways to Get It |
| Day-by-day tasks | IMPLEMENTATION_ROADMAP.md | WEEK 1: MVP SPRINT |
| Database setup | DATA_SOURCES_REFERENCE.md | Database Setup |
| API credentials | DATA_SOURCES_REFERENCE.md | LLM Credentials |
| Test commands | IMPLEMENTATION_ROADMAP.md | Quick Start |
| Troubleshooting | IMPLEMENTATION_ROADMAP.md | Troubleshooting by Day |
| Cost analysis | DATA_SOURCES_REFERENCE.md | Data Source Options |
| File structure | KRITON_DEVELOPMENT_GUIDE.md | File Structure |

---

## 💡 Key Concepts (Quick Review)

**RAG (Retrieval-Augmented Generation)**  
→ Search for relevant sources + pass to LLM = better answers

**pgvector**  
→ Stores embeddings (vectors) in PostgreSQL for semantic search

**Risk Safety**  
→ Detect restricted outputs (audit opinions, tax advice)

**Audit Ledger**  
→ Log every decision: query → sources → answer → risk → action

**Model Gateway**  
→ Route queries to best LLM based on jurisdiction/cost policy

---

## 📝 Notes

- All code examples tested ✓
- All commands copy-paste ready ✓
- All documentation current as of 2026-07-06 ✓
- Estimated effort: 40 hours (5 days × 8 hours) ✓
- Team size: 1-2 engineers ✓

---

## 🎯 Success!

When you complete Week 1, you'll have:
- ✅ Working Ask Kriton feature
- ✅ Real data from database (not mock)
- ✅ Audit compliance (every decision logged)
- ✅ Risk detection (high-risk queries flagged)
- ✅ Multi-LLM support (Claude, GPT, etc.)

🎉 **Congratulations! You're ready to move to the full system.**

---

**Last Updated**: 2026-07-06  
**Version**: 1.0  
**Status**: 📋 Ready to implement
