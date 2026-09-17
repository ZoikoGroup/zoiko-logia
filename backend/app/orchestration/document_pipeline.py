"""Planning and deterministic analysis for uploaded-document questions.

Gemini remains the report writer. This module decides how much evidence to
load and computes basic spreadsheet KPIs before any model sees the data.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.orchestration.websearch import WebSource


_GENERATION = re.compile(
    r"\b(generate|create|prepare|draft|produce|write|export)\b.*\b(report|summary|analysis|document|workbook|presentation|slides?|statement|working paper|reconciliation|schedule|profit.?and.?loss|p\s*&\s*l)\b",
    re.IGNORECASE,
)
_SUMMARY = re.compile(r"\b(summarize|summarise|overview|management report|executive summary)\b", re.IGNORECASE)


@dataclass(frozen=True)
class DocumentTaskPlan:
    task_type: str
    retrieval_mode: str
    output_format: str = "chat"
    response_mode: str = "chat"


def plan_document_task(query: str, *, has_documents: bool) -> DocumentTaskPlan:
    """Fast deterministic guardrail around the Gemini writing stage.

    A second model call just to decide whether "generate a report" means full
    document retrieval adds latency and another failure point. The planner is
    deliberately deterministic for obvious generation intents; Gemini handles
    the semantic/report-writing work after verified evidence is assembled.
    """
    lowered = query.lower()
    format_patterns = (
        ("pdf", r"\bpdf\b"),
        ("pptx", r"(?:\bpptx?\b|\bpowerpoint\b|\bslide deck\b|\bpresentation\b)"),
        ("xlsx", r"(?:\bxlsx?\b|\bas (?:an? )?(?:excel|spreadsheet)\b|\bexcel (?:report|workbook|file)\b)"),
        ("docx", r"(?:\bdocx?\b|\bas (?:a )?word\b|\bword document\b)"),
        ("md", r"(?:\.md\b|\bmarkdown\b)"),
    )
    output_format = next(
        (kind for kind, pattern in format_patterns if re.search(pattern, lowered)), "chat"
    )
    if has_documents and _GENERATION.search(query):
        if output_format == "chat":
            if re.search(r"\b(working paper|reconciliation|schedule)\b", lowered):
                output_format = "xlsx"
            elif re.search(r"\b(print-ready|board report)\b", lowered):
                output_format = "pdf"
            else:
                output_format = "docx"
        return DocumentTaskPlan("document_generation", "full_document", output_format, "chat_with_artifact")
    # A plain summary request needs complete-document evidence, but it is still
    # a chat response. Only an explicit create/generate/export instruction may
    # produce a downloadable artifact.
    if has_documents and _SUMMARY.search(query):
        return DocumentTaskPlan("document_summary", "full_document", "chat", "chat")
    return DocumentTaskPlan("document_question", "targeted", output_format)


def _number(value: str) -> Decimal | None:
    cleaned = value.strip().replace(",", "").replace("$", "").replace("£", "").replace("€", "")
    if not cleaned or cleaned.startswith("="):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def analyse_spreadsheet_sources(sources: list[WebSource]) -> dict:
    """Compute common accounting KPIs from tab-delimited workbook evidence.

    Only detail tables are aggregated. Summary sheets/rows are retained as
    evidence but excluded from totals to avoid double counting.
    """
    totals: dict[str, Decimal] = defaultdict(Decimal)
    customers: dict[str, Decimal] = defaultdict(Decimal)
    products: dict[str, Decimal] = defaultdict(Decimal)
    rows_analysed = 0
    evidence: list[str] = []
    for source in sources:
        lines = [line.split("\t") for line in source.snippet.splitlines() if "\t" in line]
        if len(lines) < 2:
            continue
        headers = [cell.strip().lower().replace("_", " ") for cell in lines[0]]
        revenue_index = next((i for i, h in enumerate(headers) if h in {"revenue", "sales", "amount"} or h.startswith("revenue ")), None)
        if revenue_index is None:
            continue
        # A detail table normally has a customer/product/date dimension. This
        # excludes pre-aggregated Summary sheets from total calculations.
        customer_index = next((i for i, h in enumerate(headers) if h in {"customer", "client", "customer name", "client name"}), None)
        if customer_index is None:
            customer_index = next((i for i, h in enumerate(headers) if "customer" in h or "client" in h), None)
        product_index = next((i for i, h in enumerate(headers) if "product" in h or "service" in h), None)
        date_index = next((i for i, h in enumerate(headers) if h == "date" or "period" in h), None)
        if customer_index is None and product_index is None and date_index is None:
            continue
        metric_indexes = {
            "total_revenue": revenue_index,
            "total_cost": next((i for i, h in enumerate(headers) if h in {"cost", "costs", "total cost"} or h.startswith("cost ")), None),
            "gross_profit": next((i for i, h in enumerate(headers) if "gross profit" in h or h.startswith("profit ") or h == "profit"), None),
        }
        for row in lines[1:]:
            revenue = _number(row[revenue_index]) if revenue_index < len(row) else None
            if revenue is None:
                continue
            rows_analysed += 1
            for metric, index in metric_indexes.items():
                if index is not None and index < len(row):
                    value = _number(row[index])
                    if value is not None:
                        totals[metric] += value
            if customer_index is not None and customer_index < len(row) and row[customer_index].strip():
                customers[row[customer_index].strip()] += revenue
            if product_index is not None and product_index < len(row) and row[product_index].strip():
                products[row[product_index].strip()] += revenue
        evidence.append(source.title)
    revenue = totals.get("total_revenue", Decimal(0))
    profit = totals.get("gross_profit", Decimal(0))
    result = {
        "coverage": {
            "chunks_processed": len(sources),
            "locations_processed": [source.title for source in sources],
            "complete": True,
        },
        "rows_analysed": rows_analysed,
        "metrics": {key: float(value) for key, value in totals.items()},
        "customer_revenue": {key: float(value) for key, value in sorted(customers.items(), key=lambda item: item[1], reverse=True)},
        "product_revenue": {key: float(value) for key, value in sorted(products.items(), key=lambda item: item[1], reverse=True)},
        "evidence_locations": evidence,
    }
    if revenue:
        result["metrics"]["gross_margin_percent"] = float((profit / revenue) * 100)
    return result


def build_document_generation_prompt(query: str, sources: list[WebSource], analysis: dict) -> str:
    # Bound external-model context so one huge workbook cannot exhaust the
    # model window or monopolise a worker. Divide the budget across sources so
    # later sheets are not silently crowded out by the first one.
    total_budget = 60_000
    # Keep the aggregate evidence body bounded even for workbooks containing
    # hundreds of chunked sheet ranges. Deterministic analysis above still
    # consumes every chunk; this cap applies only to prose-generation context.
    per_source = max(120, min(6_000, total_budget // max(len(sources), 1)))
    evidence = "\n\n".join(
        f"[REF-{index}] {source.title}\n{source.snippet[:per_source]}"
        for index, source in enumerate(sources, start=1)
    )
    return (
        "You are generating a professional accounting document from an uploaded file.\n"
        "Use ONLY the evidence and verified calculations below. Do not use external knowledge.\n"
        "Do not alter or independently recalculate verified figures. If requested information is absent, say so.\n"
        "Produce the requested sections with a concise executive summary and clear Markdown tables.\n"
        "Do not print REF markers in the prose; citations are attached separately by Kriton.\n\n"
        f"=== Verified deterministic analysis ===\n{json.dumps(analysis, indent=2)}\n\n"
        f"=== Uploaded document evidence ===\n{evidence}\n\n"
        f"=== User request ===\n{query}"
    )
