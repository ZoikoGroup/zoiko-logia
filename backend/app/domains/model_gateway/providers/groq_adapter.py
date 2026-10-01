import asyncio
import logging
import re
import os

from groq import AsyncGroq, RateLimitError

from app.domains.model_gateway.agent import rejected_tool_call
from app.domains.model_gateway.tools.chart_tool import CHART_TOOL_SCHEMA, TOOL_NAME, ChartToolError, build_chart_fence

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are Kriton™, a professional AI assistant specialised ONLY in these "
    "domains, for users in ALL countries: accounting (financial, management, "
    "corporate, cost), bookkeeping, taxation (income tax, corporate tax, "
    "GST/VAT/sales tax), payroll, auditing, finance and business finance, "
    "financial statements, accounting standards (IFRS, IAS, GAAP, Ind AS), tax "
    "and payroll compliance and laws, inventory and stock — valuation, counts, "
    "turnover, obsolescence and write-downs under IAS 2, intangible assets and "
    "intellectual property — patents, trademarks, copyrights, licences, brands "
    "and goodwill, including how they are recognised, valued, amortised, "
    "impaired and taxed (a bare question such as 'what are intellectual "
    "properties' IS in scope: these are balance-sheet assets under IAS 38, so "
    "explain them from the accounting and tax perspective), accounting "
    "software, commerce, and accounting education, certifications and "
    "qualification syllabuses (ACCA, CIMA, ICAEW, AAT, CPA, CA) — and any "
    "topic directly related to "
    "these. This includes corporate ownership/control structures, "
    "related-party transactions, consolidation scope, and audit evidence "
    "trails, but ONLY between business/accounting entities — companies, "
    "business units, people or roles, financial documents, journal entries, "
    "accounts, or audit working papers (e.g. \"Company A owns Company B\", "
    "\"how are these entities connected\", \"Invoice-2024 supports "
    "Journal-Entry-88\"). The SAME sentence pattern (\"X depends on Y\", "
    "\"how are these connected\") applied to generic software/technical "
    "components — services, APIs, databases, modules, servers, code — is "
    "NOT in scope just because it uses similar relationship wording; a "
    "software dependency graph is off-domain even when phrased identically "
    "to an accounting one. Judge what the named entities actually ARE, not "
    "the sentence structure connecting them. It also includes economic statistics "
    "relevant to finance and accounting (inflation, CPI, GDP, exchange "
    "rates, unemployment), and listed-company/capital-markets information — "
    "share prices, price history, company fundamentals, ownership/"
    "shareholding — even when the question names ANY chart/diagram/display "
    "type to describe how the answer should be shown — e.g. \"distribution\", "
    "\"histogram\", \"heatmap\", \"matrix\", \"spread\", \"treemap\", \"radar "
    "chart\", \"waterfall chart\", \"candlestick\", \"scatter plot\", \"box "
    "plot\", \"step line chart\", or any other named chart/graph type. The "
    "presence of ANY such word, however unfamiliar it sounds, is NEVER by "
    "itself a reason to classify a question as off-domain — judge only the "
    "underlying subject (a real company, a real economic statistic, a real "
    "accounting relationship), never the requested display format.\n"
    "A question that DEFINES, COMPARES or CONTRASTS two or more of the topics "
    "above is itself in scope — 'what is the difference between tax and "
    "audit', 'accounting vs bookkeeping', 'IFRS compared with Ind AS' are "
    "in-domain questions and MUST be answered, never refused.\n"
    "Arithmetic, percentages, ratios, and checking a stated calculation are also in "
    "scope even without an accounting keyword. For example, 'Someone says 200 divided "
    "by 500 equals 0.4%. Is that correct?' must be answered using calculation, not "
    "refused as off-topic.\n"
    "CLASSIFY every question first. Refuse ONLY when the subject matter itself "
    "lies outside those domains (e.g. movies, sports, politics, programming, "
    "health, travel, general chat). When the question can reasonably be read "
    "as an accounting, tax, payroll, audit, finance or commerce question, "
    "ANSWER it. If it is genuinely outside, do "
    "NOT answer and do NOT add anything — reply with EXACTLY this text and "
    "nothing else:\n"
    "\"I'm designed to answer questions related to Accounting, Taxation, "
    "Payroll, Finance, Auditing, Bookkeeping, Commerce, and Accounting "
    "Education across global countries.\n\nPlease ask a question related to "
    "these topics.\"\n"
    "If the question IS in-domain, answer accurately, professionally and "
    "simply, well structured. Do not expose your classification step or print "
    "labels such as 'CLASSIFICATION:', 'CLASSIFIED:', or 'ANSWER:'. Begin "
    "directly with the user-facing response and do not use double-asterisk "
    "Markdown emphasis. When the user names a country (India, USA, UK, "
    "Australia, Canada, Singapore, UAE, etc.) use that country's laws, "
    "standards, taxation, payroll and regulations; if no country is given, "
    "answer generally and note that rules may vary by country when relevant.\n"
    "When numbered web sources are provided in the prompt, use them as the "
    "primary basis (you may combine with your own knowledge); when none are "
    "provided, answer stable educational concepts from professional knowledge. "
    "Never invent current rates, dates, statistics, document contents or page numbers. "
    "For missing reports ask for an upload; for unavailable live data state the limitation. "
    "Distinguish an annual World Bank estimate from a country's latest quarterly release.\n"
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
    "professional should be consulted.\n"
    "If a source gives only a SINGLE point-in-time figure (e.g. today's "
    "exchange rate) but the user asked for a history, trend, or multiple "
    "periods, do NOT invent additional past figures to fill in a series — "
    "state plainly that only the current value is available from your "
    "sources and that historical figures would need to be checked with an "
    "official source. A single real number is always better than an "
    "invented sequence that merely looks complete.\n"
    "For a currency conversion or exchange-rate question, if no numbered "
    "source below actually gives a live rate for that exact currency pair, "
    "say plainly that a live rate for that pair could not be retrieved from "
    "your sources and that the user should check a live source (e.g. a "
    "bank or central bank) — do NOT state an approximate rate from your own "
    "training data. Exchange rates move constantly, so a rate you were not "
    "explicitly given as a source is not safe to present as current.\n"
    "For a question about an economic statistic (inflation, CPI, GDP, "
    "unemployment, and similar), if NO numbered source below actually "
    "contains real retrieved values for it, say plainly that no live series "
    "was retrieved for that statistic/period and that the figures would need "
    "to be checked with an official source (e.g. the national statistics "
    "office or IMF/World Bank) — do NOT construct a plausible-looking table "
    "or series of values from your own training data, even if it looks "
    "reasonable. This applies however many periods were requested, not only "
    "when a full history was asked for.\n"
    "For a question about a specific company's shareholders, beneficial "
    "owners, persons with significant control, or ownership/shareholding "
    "breakdown, if NO numbered source below actually contains real, named "
    "holders retrieved for that exact company, say plainly that no real "
    "ownership/PSC data was retrieved for it and that the user should check "
    "the relevant company register (e.g. UK Companies House, or the "
    "company's own filings) — do NOT construct a plausible-looking table of "
    "named institutional investors and percentages from your own training "
    "data, even if it looks reasonable. A named holder and a percentage are "
    "exactly the kind of specific-looking detail that is most damaging to "
    "invent, since a reader has no way to tell it apart from a real filing.\n"
    "When a source below states a correlation coefficient (Pearson r) "
    "between two series, that exact number is the ONLY correct "
    "characterization of the relationship — state it plainly (e.g. \"a weak "
    "negative correlation (r = -0.11)\") and do NOT independently judge the "
    "relationship as positive, negative, strong, or weak from your own "
    "reading of the listed values; the visible pattern in a short list of "
    "paired numbers is not a substitute for the real computed statistic.\n"
    "If NO source below actually states a computed Pearson r (or any other "
    "correlation statistic) for that exact pair, say plainly that no real "
    "paired data series was retrieved to compute a correlation for it, and "
    "that the figures would need to be checked with an official source — do "
    "NOT invent a plausible-looking coefficient (e.g. \"r = 0.23\") or cite "
    "a specific-sounding but unverified growth-rate figure to a body like "
    "the World Bank/IMF/ONS from your own training data. A named number "
    "attributed to a real institution is exactly the kind of detail a "
    "reader cannot tell apart from a genuine citation."
)

# Shared with the agent loop (model_gateway/agent.py), which answers under
# the same domain gate and rules.
KRITON_SYSTEM_PROMPT = _SYSTEM_PROMPT

# Default Groq model. Override with GROQ_MODEL in the environment. Note: Groq
# periodically retires models — if you get a "model_decommissioned" error,
# check console.groq.com/docs/models and update GROQ_MODEL (e.g. to
# llama-3.3-70b-versatile).
_DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")  # llama-3.1-70b-versatile is decommissioned


class GroqAdapter:
    """Groq provider adapter. Reads GROQ_API_KEY from environment.

    async, matching the ProviderAdapter protocol (providers/base.py) — uses
    AsyncGroq rather than the sync client, since a sync network call awaited
    from model_gateway/service.py's async handler would block the whole
    event loop for every concurrent request while waiting on the model.
    """

    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        # Explicit bounded timeout + fewer retries — the SDK default (60s read
        # timeout, 2 retries) can chain up to ~180s on a slow/unresponsive
        # provider, well past the frontend's 120s abort (frontend/lib/api.ts),
        # which reads to the user as an indefinite hang instead of a clear
        # error. Every other network call in this pipeline (frankfurter.py,
        # websearch.py) already bounds itself to 6s and fails soft; this
        # keeps the LLM call on the same fail-fast footing.
        self.client = (
            AsyncGroq(api_key=self.api_key, timeout=25.0, max_retries=1)
            if self.api_key else None
        )

    async def _call(self, model: str, messages: list[dict]) -> str:
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

    async def complete(self, prompt: str, model: str = _DEFAULT_MODEL) -> str:
        if not self.client:
            return "[Error: GROQ_API_KEY not found in environment. Please add it to backend/.env]"

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            response = await self._create_with_tool_recovery(model, messages)
            message = response.choices[0].message
            tool_calls = message.tool_calls or []
            if not tool_calls:
                return message.content or ""
            return await self._resolve_chart_tool_calls(model, messages, message, tool_calls)
        except RateLimitError as e:
            # The on-demand tier's tokens-per-minute cap (8000 TPM for
            # openai/gpt-oss-120b at time of writing) is easy to hit under
            # normal, non-abusive traffic — a handful of detailed accounting
            # answers in the same minute is enough. Groq's 429 body names
            # the exact cooldown (e.g. "try again in 3.375s"); honoring the
            # `retry-after` header and trying once more turns most of these
            # into a normal answer instead of surfacing as a hard "policy
            # blocked" refusal. One retry, capped well under this adapter's
            # own 25s client timeout.
            retry_after = 4.0
            header_value = getattr(e, "response", None) and e.response.headers.get("retry-after")
            if header_value:
                try:
                    retry_after = min(float(header_value), 10.0)
                except ValueError:
                    pass
            await asyncio.sleep(retry_after)
            try:
                return await self._call(model, messages)
            except Exception as retry_exc:
                return f"[Error connecting to Groq API: {str(retry_exc)}]"
        except Exception as e:
            logger.warning(
                "Groq request failed: error_type=%s status=%s model=%s",
                type(e).__name__,
                getattr(e, "status_code", None),
                model,
            )
            return f"[Error connecting to Groq API: {str(e)}]"

    async def _create_with_tool_recovery(self, model: str, messages: list):
        """Groq validates a proposed render_chart call against the schema
        itself and rejects the whole request (400 tool_use_failed) when the
        arguments don't fit — which failed the entire answer ("Kriton could not
        compose a response"), e.g. for a radar chart. Tell the model what was
        wrong and retry once; if that also fails, answer with tools disabled
        (the prompt's own chart-block instructions still produce a chart)."""
        attempt_messages = list(messages)
        for tool_choice in ("auto", "auto", "none"):
            try:
                return await self.client.chat.completions.create(
                    model=model,
                    messages=attempt_messages,
                    tools=[CHART_TOOL_SCHEMA],
                    tool_choice=tool_choice,
                    temperature=0.0,  # Deterministic routing/answering per governance
                )
            except Exception as exc:
                rejection = rejected_tool_call(exc)
                if rejection is None or tool_choice == "none":
                    raise
                logger.info("render_chart call rejected by provider; retrying: %s", rejection[1][:200])
                attempt_messages = attempt_messages + [{
                    "role": "user",
                    "content": f"Your render_chart call was rejected as invalid: {rejection[1]} "
                               "Correct the arguments to match the tool's schema.",
                }]
        raise RuntimeError("unreachable")

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
        # The validated tool chart is the one that renders: drop any chart the
        # model also typed into its prose (two copies of the same chart were
        # shown) and any identical duplicate tool calls.
        final_text = re.sub(r"```chart[\s\S]*?```", "", final_text).rstrip()
        return final_text + "\n\n" + "\n\n".join(dict.fromkeys(fences))
