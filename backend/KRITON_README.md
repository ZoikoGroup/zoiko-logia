# Kriton™ Implementation README

This document outlines the implementation details, functional architecture, run commands, and external services utilized in the Kriton™ Backend system (powered by the Massarius™ engine).

## 1. System Overview and Functioning

The Kriton™ backend is a RAG (Retrieval-Augmented Generation) pipeline built on **FastAPI** and **LlamaIndex**. It is designed to handle query orchestration, authoritative source ingestion, safety risk screening, and accurate response composition based on curated knowledge.

### Core Workflow: Ask Kriton™
1. **Query Ingress & Validation**: User submits a query. The backend performs structural validation.
2. **Safety & Risk Classification**: Queries are routed through a risk classifier (LLM-based) to identify restricted topics, self-harm, PII, or out-of-domain (finance/legal advice) questions.
3. **Query Routing**: The router evaluates if the query requires standard retrieval (`keyword_mvp`, `semantic`, etc.) or if it should be immediately rejected or handled via fallback.
4. **Retrieval**: Documents ingested into the vector store are queried. The system attempts to fetch the most relevant nodes based on the query.
5. **Response Composition**: A secondary LLM call synthesizes the retrieved nodes into a structured, helpful answer that adheres strictly to the retrieved context without hallucination.
6. **Audit Ledger**: The entire transaction (query, retrieved context, risk score, composed answer) is recorded for compliance.

### Document Ingestion
- Ingestion supports PDF, DOCX, and PPTX via **LlamaParse**.
- Ingested files are split, embedded, and stored in a vector database (local SQLite or cloud).

## 2. Services and Components

| Component / Function | Service / Library Utilized | Details |
| --- | --- | --- |
| **API Framework** | FastAPI | Asynchronous Python backend framework handling HTTP requests and routing. |
| **RAG Orchestration** | LlamaIndex | Core framework for document indexing, chunking, and retrieval logic. |
| **Document Parsing** | LlamaParse (LlamaCloud API) | Used to parse complex PDFs, DOCX, and PPTX files into markdown/text. |
| **Embeddings** | HuggingFace (`BAAI/bge-m3`) | Local embedding model used to convert text chunks into vector representations. |
| **Vector Store** | SQLite (Local Default) / Pinecone | Local vector store for development and testing; extensible to Pinecone for production. |
| **LLM / Generation** | Groq API (`llama3-70b-8192` / `llama3-8b-8192`) | High-speed LLM inference utilized for risk classification, routing, and final answer composition. |

## 3. Run Commands

### Backend (FastAPI)
Ensure you have activated your virtual environment and installed all dependencies from `requirements.txt`.
Make sure you have populated the `.env` file with your `GROQ_API_KEY` and `LLAMA_CLOUD_API_KEY`.

```bash
# Start the FastAPI development server
cd backend
uvicorn app.main:app --reload --port 8000
```
*The API will be available at `http://localhost:8000`. Swagger documentation is at `http://localhost:8000/docs`.*

### Frontend (Next.js / React)
```bash
# Start the frontend development server
cd frontend
npm install
npm run dev
```
*The frontend application will be available at `http://localhost:3000`.*

### Accessing the Dashboard (Login)
Once the frontend and backend servers are running, you can access the ZoikoLogia Governance Dashboard at:
- **URL**: [http://localhost:3000/login](http://localhost:3000/login)

**Default Admin Credentials:**
- **Email**: `dashboard@zoikologia.com`
- **Password**: `Password234@`

### Useful Testing Scripts
There are various scripts in the `scripts/` or root directory used for testing individual components:
- **`python test_vector_load.py`**: Tests the local SQLite vector store loading mechanism.
- **`python test_routing.py`**: Tests the LLM-based query router.
- **`python test_apis.py`**: Tests integrations and basic endpoints.

## 4. Environment Configuration (`.env`)

Before running the application, you must configure the backend environment variables. Create a `.env` file in the `backend/` directory (you can copy `.env.example` if available) and add your actual API credentials:

```env
# LLM Provider (Groq for high-speed Llama-3 inference)
GROQ_API_KEY=your_groq_api_key_here

# Document Parsing (LlamaCloud)
LLAMA_CLOUD_API_KEY=your_llama_cloud_api_key_here
```
*Note: Make sure to replace `your_groq_api_key_here` and `your_llama_cloud_api_key_here` with your actual valid API keys to ensure routing, retrieval, and document ingestion function correctly.*

## 5. Architectural Naming Conventions (ZL-ENG-01)
- **Kriton™**: The public-facing name used on all customer-visible surfaces, UI, and API responses.
- **Massarius™**: The internal reasoning engine. This name is used in codebase structures and comments but must never be exposed to the end user.
