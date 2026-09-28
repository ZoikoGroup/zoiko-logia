"""Deterministic domain semantics for visualization routing."""
from __future__ import annotations

import re

from pydantic import BaseModel


class DomainContext(BaseModel):
    domain: str = "GENERAL"
    subdomain: str = "GENERAL"
    intent: str | None = None


_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("AUDIT", "AUDIT_EVIDENCE", re.compile(r"\b(assertion|audit evidence|working paper|audit finding|audit conclusion|evidence sufficiency)\b", re.I)),
    ("AUDIT", "AUDIT_CONTROLS", re.compile(r"\b(audit|auditor|control matrix|control testing|substantive testing)\b", re.I)),
    ("TAX", "TAX_PROVISION", re.compile(r"\b(book[- ]to[- ]tax|tax provision|effective tax rate|deferred tax|current tax|tax expense)\b", re.I)),
    ("TAX", "TAX_COMPLIANCE", re.compile(r"\b(tax|taxation|VAT|GST|corporation tax|income tax|tax deadline|tax nexus)\b", re.I)),
    ("COMPLIANCE", "CONTROL_COVERAGE", re.compile(r"\b(compliance|regulatory obligation|framework mapping|control coverage|gap analysis)\b", re.I)),
    ("FRAUD_FORENSICS", "FORENSIC_ANALYTICS", re.compile(r"\b(fraud|forensic|related[- ]party|anomal(?:y|ies)|duplicate payment|suspicious transaction|Benford)\b", re.I)),
    ("RISK", "ENTERPRISE_RISK", re.compile(r"\b(risk register|risk matrix|risk appetite|risk exposure)\b", re.I)),
    ("TREASURY", "LIQUIDITY", re.compile(r"\b(treasury|liquidity|cash runway|cash burn|debt maturity|covenant|working capital)\b", re.I)),
    ("ACCOUNTS_RECEIVABLE", "ACCOUNTS_RECEIVABLE", re.compile(r"\b(accounts receivable|trade receivable|receivables?|\bAR\b|aging buckets?|collections?)\b", re.I)),
    ("ACCOUNTS_PAYABLE", "ACCOUNTS_PAYABLE", re.compile(r"\b(accounts payable|trade payable|payables?|\bAP\b|vendor exposure)\b", re.I)),
    ("FP&A", "FP_AND_A", re.compile(r"\b(FP&A|forecast|budget vs actual|scenario|sensitivity|driver analysis)\b", re.I)),
    ("SUPPLY_CHAIN", "SUPPLY_CHAIN", re.compile(r"\b(supply chain|inventory turnover|stock level|vendor performance|logistics)\b", re.I)),
    ("OPERATIONS", "OPERATIONS", re.compile(r"\b(operations|cycle time|throughput|capacity utilization|lead time)\b", re.I)),
    ("CUSTOMER_ANALYTICS", "CUSTOMER", re.compile(r"\b(customer segment|customer lifetime value|churn|retention|RFM)\b", re.I)),
    ("SALES", "SALES", re.compile(r"\b(sales funnel|sales trend|sales by|pipeline dashboard|win loss)\b", re.I)),
    ("HR_PAYROLL", "HR_PAYROLL", re.compile(r"\b(payroll|headcount|attrition|salary distribution|overtime|leave trend)\b", re.I)),
    ("PROJECT_MANAGEMENT", "PROJECT", re.compile(r"\b(project timeline|Gantt|task dependency|resource allocation|burn down|milestone)\b", re.I)),
    ("IT_ANALYTICS", "IT_ANALYTICS", re.compile(r"\b(system architecture|incident trend|SLA dashboard|release roadmap|IT analytics)\b", re.I)),
    ("ACCOUNTING", "GENERAL_LEDGER", re.compile(r"\b(trial balance|journal entr(?:y|ies)|general ledger|ledger|account reconciliation|retained earnings)\b", re.I)),
    ("ACCOUNTING", "FINANCIAL_STATEMENTS", re.compile(r"\b(balance sheet|income statement|cash flow statement|financial statement|accounting|bookkeeping|invoice approval)\b", re.I)),
    ("FINANCE", "FINANCIAL_ANALYSIS", re.compile(r"\b(finance|financial|revenue|profit|cost|inflation|CPI|exchange rate|currency)\b", re.I)),
)


def classify_domain_context(query: str, intent: str | None = None) -> DomainContext:
    for domain, subdomain, pattern in _RULES:
        if pattern.search(query or ""):
            return DomainContext(domain=domain, subdomain=subdomain, intent=intent)
    return DomainContext(intent=intent)


def domain_variant(base_variant: str, context: DomainContext, query: str = "") -> str:
    """Specialize only implemented canonical visuals; never changes shape."""
    q = query.lower()
    if base_variant == "EVIDENCE_GRAPH":
        if context.subdomain == "AUDIT_EVIDENCE":
            return "ASSERTION_EVIDENCE_GRAPH"
        if context.domain == "AUDIT":
            return "AUDIT_TRAIL_GRAPH"
        if context.domain == "COMPLIANCE":
            return "CONTROL_EVIDENCE_GRAPH"
    if base_variant in {"BASIC_FLOWCHART", "INTERACTIVE_WORKFLOW"}:
        if context.subdomain == "GENERAL_LEDGER" and "journal" in q:
            return "JOURNAL_ENTRY_FLOW"
        if context.domain == "AUDIT":
            return "AUDIT_CONTROL_FLOW"
        if context.domain == "TAX":
            return "TAX_COMPLIANCE_FLOW"
        if context.domain == "ACCOUNTING":
            return "ACCOUNTING_PROCESS_FLOW"
    if base_variant == "STANDARD_HISTOGRAM" and context.domain == "AUDIT":
        return "AUDIT_SAMPLING_DISTRIBUTION"
    if base_variant == "STANDARD_LINE":
        if context.domain == "ACCOUNTS_RECEIVABLE":
            return "AR_COLLECTION_TREND"
        if context.domain == "ACCOUNTS_PAYABLE":
            return "AP_PAYMENT_TREND"
        if context.domain == "TREASURY":
            return "LIQUIDITY_TREND"
        if context.domain == "TAX":
            return "TAX_METRIC_TREND"
    return base_variant
