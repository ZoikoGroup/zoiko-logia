# Complete composition context packing

The repeated VAT request (`corr-a0a0f0aa7e92`) still failed after removing
duplicated instructions. Read-only audit inspection confirmed the new server
had reloaded, retrieval succeeded, and standard composition failed its size
preflight before answer generation. The earlier regression checked only a
subset of the assembled context; it did not establish that this actual
combination would fit.

This bundle selected eight registered passages totalling 4,405 characters,
in addition to web evidence, seven conversation-history messages and
request-specific instructions. Individually bounded blocks did not share a
single composition allowance.

The standard path now measures the fully assembled prompt with its system
instructions and chart schema. It reserves 1,024 estimated tokens for an
answer plus 256 for template/redaction overhead. When necessary, it rebuilds
explicitly identified evidence and history sections at smaller allowances
until the combined estimate fits. Current question text and fixed instructions
are preserved. It does not locate sections by parsing untrusted marker text.

Registered evidence retains its reference and passage identifiers. Focused
excerpts are marked as shortened. The immutable retrieval manifest remains
unchanged. History selection retains complete messages with user inputs taking
priority over assistant prose; omissions are declared. If fixed content alone
cannot fit, it stays intact and the existing gateway preflight still rejects
the request rather than silently altering the question. This is standard
composition packing, not general compaction of every agent tool transcript.

Safe diagnostic logs record query ID, estimated input before/after packing
and the configured limit. They do not log prompts, source text or credentials.

Offline regressions cover web evidence, eight registered passages, history
and extra instructions together, stable reference IDs, preservation of fixed
text, impossible-to-fit input and actual production orchestration assembly.
The focused context and request-size tests pass (23 tests). No model calls,
credential changes or shared database writes were performed. Live answer
quality and provider token counts remain unverified.

Full offline backend suite: 3,207 passed, 21 skipped, 2 expected failures and
134 warnings. The local backend reloaded successfully after the changes.
