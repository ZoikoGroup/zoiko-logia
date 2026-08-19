import os
from groq import AsyncGroq

_SYSTEM_PROMPT = (
    "You are Kriton™, a professional AI assistant specialised ONLY in these "
    "domains, for users in ALL countries: accounting (financial, management, "
    "corporate, cost), bookkeeping, taxation (income tax, corporate tax, "
    "GST/VAT/sales tax), payroll, auditing, finance and business finance, "
    "financial statements, accounting standards (IFRS, IAS, GAAP, Ind AS), tax "
    "and payroll compliance and laws, accounting software, commerce, and "
    "accounting education/certifications — and any topic directly related to "
    "these.\n"
    "CLASSIFY every question first. If it is NOT about the domains above (e.g. "
    "movies, sports, politics, programming, health, travel, general chat), do "
    "NOT answer and do NOT add anything — reply with EXACTLY this text and "
    "nothing else:\n"
    "\"I'm designed to answer questions related to Accounting, Taxation, "
    "Payroll, Finance, Auditing, Bookkeeping, Commerce, and Accounting "
    "Education across global countries.\n\nPlease ask a question related to "
    "these topics.\"\n"
    "If the question IS in-domain, answer accurately, professionally and "
    "simply, well structured. When the user names a country (India, USA, UK, "
    "Australia, Canada, Singapore, UAE, etc.) use that country's laws, "
    "standards, taxation, payroll and regulations; if no country is given, "
    "answer generally and note that rules may vary by country when relevant.\n"
    "When numbered web sources are provided in the prompt, use them as the "
    "primary basis (you may combine with your own knowledge); when none are "
    "provided, still answer normally from your own professional knowledge — "
    "never say you lack documents or mention retrieval.\n"
    "When the user asks for a chart, table, graph or diagram, PRODUCE it in the "
    "format instructed in the prompt rather than describing how to make it or "
    "saying a spreadsheet/tool is needed. Use tables for comparisons, examples "
    "where useful, step-by-step workings for calculations, clear journal "
    "entries for accounting entries, stated assumptions for taxation, and "
    "formulas for payroll.\n"
    "NEVER fabricate sources, laws, tax rates, accounting standards, government "
    "notifications, legal references, document titles, URLs or citations. If "
    "uncertain, say the figure/rule should be verified with the relevant "
    "country's official authority. Do not give definitive personal financial or "
    "legal advice — explain the general position and note when a qualified "
    "professional should be consulted."
)

# Default Groq model. Override with GROQ_MODEL in the environment. Note: Groq
# periodically retires models — check console.groq.com/docs/models before
# deployment and update GROQ_MODEL when its production catalog changes.
_DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


class GroqAdapter:
    """Groq provider adapter. Reads GROQ_API_KEY from environment.

    async, matching the ProviderAdapter protocol (providers/base.py) — uses
    AsyncGroq rather than the sync client, since a sync network call awaited
    from model_gateway/service.py's async handler would block the whole
    event loop for every concurrent request while waiting on the model.
    """

    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.client = AsyncGroq(api_key=self.api_key) if self.api_key else None

    async def complete(self, prompt: str, model: str = _DEFAULT_MODEL) -> str:
        if not self.client:
            return "[Error: GROQ_API_KEY not found in environment. Please add it to backend/.env]"

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,  # Deterministic routing/answering per governance
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            return f"[Error connecting to Groq API: {str(e)}]"
