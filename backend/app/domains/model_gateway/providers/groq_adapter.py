import os
from groq import AsyncGroq

_SYSTEM_PROMPT = (
    "You are Kriton™, a helpful professional advisor. Answer based only on "
    "the provided context. If no context is provided, state that you cannot "
    "answer without sufficient source material. When a single source passage "
    "discusses more than one related technical term (e.g. a passage covering "
    "both 'test of controls' and 'substantive procedures'), attribute each "
    "definition only to the exact term it actually describes — do not swap "
    "or blend the definition of one term onto a different, adjacent term "
    "just because they appear in the same passage. When your answer reports "
    "three or more comparable numeric values across categories, line items, "
    "or periods (e.g. a cost breakdown, ratio comparison, or budget vs. "
    "actual), present those values as a markdown table (header row plus a "
    "|---|---| separator row) rather than a bulleted list or prose — but "
    "only using numbers that actually appear in the provided context; never "
    "invent or estimate figures to populate a table. Numbers the user states "
    "directly in their own question are legitimate data to use and to "
    "tabulate — the provided context includes the user's own message, not "
    "only retrieved source text. When a category, line item, period, or "
    "entity has more than one associated numeric measure (for example "
    "headcount, revenue, and margin for the same region), give each measure "
    "its own column in that same table — never collapse multiple requested "
    "measures into a single column, and never drop a requested measure. "
    "Never fabricate an illustrative table filled with placeholder text "
    "such as 'the applicable amount' in place of a real figure — a table "
    "cell must contain either a real number drawn from the context or "
    "nothing at all; if you do not have concrete figures to populate a "
    "table, explain the concept in prose instead of inventing an empty "
    "or placeholder table. Any markdown table you do produce must be "
    "syntactically complete: the |---|---| separator row goes immediately "
    "beneath the header row, before any data rows — never after the data, "
    "and never left dangling as stray '|---|' text elsewhere in the answer."
)


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

    # routing_fallback.py's complete_with_fallback() calls complete(prompt)
    # with no model argument, so the ModelDefinition row selected by
    # _select_model_and_adapter() only ever picks the PROVIDER — this default
    # is what actually decides the model. Changing the registry row's
    # `version` therefore has no effect on behaviour; it must be changed here.
    #
    # Was llama-3.1-8b-instant. An 8B model handed one retrieved passage and
    # asked to explain it reproduces that passage close to verbatim, which is
    # exactly what composition validation's "Summarize-don't-copy" check
    # rejects — and the automatic repair pass in orchestration/service.py
    # retries through this same adapter, so it failed identically and the
    # answer degraded to a clarification. The repetition-loop problem
    # documented in the temperature comment below is the same weakness.
    # 70b-versatile paraphrases rather than copies.
    #
    # Overridable so a model can be swapped without a code change, matching
    # how RISK_LLM_CLASSIFIER_MODEL is handled for the classifier.
    async def complete(
        self,
        prompt: str,
        model: str = "",
    ) -> str:
        model = model or os.environ.get("GROQ_ANSWER_MODEL", "").strip() or "llama-3.3-70b-versatile"
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
                # temperature=0.0 is pure greedy decoding — confirmed prone to
                # degenerate repetition loops on this model (llama-3.1-8b-instant)
                # when the retrieved context is thin/conflicting (a real answer
                # got stuck repeating the same paragraph ~20x instead of
                # stopping). frequency_penalty=0.4 alone wasn't sufficient — a
                # second real case (confusing, badly-labeled bracket data)
                # still looped through 3+ repeats before hitting max_tokens.
                # Raised to 0.7 and tightened the token cap so any residual
                # loop is caught much sooner. This is a fixed post-hoc logit
                # adjustment, not stochastic sampling, so determinism
                # (same input -> same output) is unaffected.
                # Kept at 0.7 despite the model change — it is a fixed logit
                # adjustment, costs nothing when the model is not looping, and
                # the 8B model remains reachable through GROQ_ANSWER_MODEL.
                frequency_penalty=0.7,
                # Was 900, chosen to cut the 8B model's repetition loops short.
                # That cap is too tight for the "Tutor-depth structure" check,
                # which wants a structured explanation (purpose, supported
                # example, qualifications) before the mandatory disclaimers are
                # appended — a truncated answer fails it on length alone. The
                # repetition risk this guarded against was specific to
                # llama-3.1-8b-instant; drop this back to 900 if a 70b answer
                # ever loops.
                max_tokens=1400,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            return f"[Error connecting to Groq API: {str(e)}]"
