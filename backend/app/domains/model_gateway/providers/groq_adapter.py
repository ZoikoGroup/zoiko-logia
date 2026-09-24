import logging
import os
from groq import AsyncGroq

from app.domains.model_gateway.tools.chart_tool import CHART_TOOL_SCHEMA, TOOL_NAME, ChartToolError, build_chart_fence

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are Kriton™, a professional AI assistant specialised ONLY in these "
    "domains, for users in ALL countries: accounting (financial, management, "
    "corporate, cost), bookkeeping, taxation (income tax, corporate tax, "
    "GST/VAT/sales tax), payroll, auditing, finance and business finance, "
    "financial statements, accounting standards (IFRS, IAS, GAAP, Ind AS), tax "
    "and payroll compliance and laws, accounting software, commerce, and "
    "accounting education/certifications — and any topic directly related to "
    "these.\n"
    "CLASSIFY every question first, by the SUBJECT MATTER being asked about, "
    "never by the presentation format requested — a request to chart, diagram "
    "or visualise revenue, profit, expenses, cash flow, portfolio allocation "
    "or any other figure from the domains above IS in scope even when it "
    "leads with a chart/diagram type word (sankey, treemap, waterfall, "
    "flowchart, heatmap, etc.) that sounds generic on its own. If it is NOT "
    "about the domains above (e.g. "
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
    "saying a spreadsheet/tool is needed. For a data chart specifically, call "
    "the render_chart tool with the real figures rather than writing the "
    "chart's JSON yourself in the answer text — pick whichever of its "
    "supported types actually matches the data (never force a type it "
    "doesn't fit). Use tables for comparisons, examples "
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
# periodically retires models — if you get a "model_decommissioned" error,
# check console.groq.com/docs/models and update GROQ_MODEL (e.g. to
# llama-3.3-70b-versatile).
_DEFAULT_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")


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

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                tools=[CHART_TOOL_SCHEMA],
                tool_choice="auto",
                temperature=0.0,  # Deterministic routing/answering per governance
            )
            message = response.choices[0].message
            tool_calls = message.tool_calls or []
            if not tool_calls:
                return message.content or ""
            return await self._resolve_chart_tool_calls(model, messages, message, tool_calls)
        except Exception as e:
            logger.warning(
                "Groq request failed: error_type=%s status=%s model=%s",
                type(e).__name__,
                getattr(e, "status_code", None),
                model,
            )
            return f"[Error connecting to Groq API: {str(e)}]"

    async def _resolve_chart_tool_calls(self, model: str, messages: list, message, tool_calls) -> str:
        """Validate each render_chart call the model made, tell it the
        outcome, and let it write the final prose now that it knows whether
        the chart actually rendered — the standard function-calling round
        trip. The fenced ```chart block returned to the caller is always
        built from the validated arguments, never from the model's own
        retelling of them, so a chart the frontend renders can never
        disagree with the type/data the model actually requested."""
        fences: list[str] = []
        # A minimal, hand-built assistant message — not message.model_dump().
        # The full dump carries extra response-only fields (e.g. `annotations`)
        # that some Groq models reject outright when echoed back as request
        # input ("property 'annotations' is unsupported"), so only the fields
        # a request message actually accepts are forwarded.
        assistant_message = {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in tool_calls
            ],
        }
        follow_up = messages + [assistant_message]
        for call in tool_calls:
            if call.function.name != TOOL_NAME:
                tool_result = f"Unknown tool '{call.function.name}'."
            else:
                try:
                    fence = build_chart_fence(call.function.arguments)
                    fences.append(fence)
                    tool_result = "Chart rendered successfully. Do not restate its JSON — it will be attached automatically."
                except ChartToolError as exc:
                    logger.warning("render_chart arguments failed validation: %s", exc)
                    tool_result = (
                        f"The chart could not be rendered ({exc}). Explain what data is "
                        "missing instead of describing a chart that was not created."
                    )
            follow_up.append({"role": "tool", "tool_call_id": call.id, "content": tool_result})

        # tool_choice="none" must be explicit here, not just omitting `tools` —
        # a model that keeps chasing an invalid type (e.g. "gauge") after a
        # validation failure will try to call render_chart again on this turn
        # too, and Groq hard-rejects that against an implicit "none" with
        # "Tool choice is none, but model called a tool" instead of silently
        # ignoring it. Declaring the tool but forbidding its use is what
        # actually stops that.
        final = await self.client.chat.completions.create(
            model=model, messages=follow_up, tools=[CHART_TOOL_SCHEMA], tool_choice="none", temperature=0.0,
        )
        final_text = final.choices[0].message.content or ""
        if not fences:
            return final_text
        return final_text.rstrip() + "\n\n" + "\n\n".join(fences)
