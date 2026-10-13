# Recurring answer failures — 8 October 2026

The completed regression report had nine failures (50/59 passed). Its intermediate console output showed only eight because the last VAT-threshold case had not completed.

## Causes and changes

- **Calculation inputs were interpreted as research instructions.** “Current assets” and two currency symbols triggered a latest-FX requirement. Latest-FX detection now requires exchange-rate/conversion intent and excludes accounting labels, explicit historical dates and negated latest-rate instructions.
- **The model changed user-supplied inputs.** A 12% combined GST calculation became an 18% calculation. Explicit intra-state CGST/SGST splits now run through Decimal arithmetic before retrieval. Negative, multiple and ambiguous inputs are rejected rather than silently reduced to one calculation.
- **Numbered calculations depended on model transcription.** The CAGR result was rounded incorrectly and the displayed exponent was broken. Supported numbered finance calculations now execute independently, keeping each question’s inputs and currency separate. Unsupported batches return to the general pipeline instead of dropping questions.
- **Search missed the applicable official material.** Relevant authority entry pages are fetched alongside search. India’s trusted-source list now includes CBIC’s GST site, the GST Council and India Code. A combined registration/export question now searches both topics rather than returning after registration search.
- **Evidence lost its meaning when shortened.** Goods, services and state-dependent limits are kept together. LUT guidance is prioritised in the export FAQ excerpt. A simple current Singapore rate answer is derived from IRAS’s explicit current-rate statement, canonical URL and current retrieval date; historical and compound questions are excluded from that shortcut.
- **Valid special rules were used for the wrong purpose.** Release checks reject unqualified ring-fence rates for ordinary-company questions, unqualified state-specific service limits and monthly registration liability mislabelled as composition-scheme eligibility. Current HMRC evidence resolves a quoted VAT-threshold claim without treating an older freeze announcement as equally current.
- **Incomplete answers could pass weak tests.** The India registration check now requires goods and services coverage. Export acceptance requires zero-rating and LUT/Letter of Undertaking coverage. Runtime coverage also requires export qualification conditions. A narrow source-bound Karnataka service-export explanation requires retrieved evidence for all three rules and states the turnover and qualification assumptions; it embeds no threshold amount.
- **The evaluation server could run old code.** Port 8010 used reload, while the server on 8011 did not. The evaluation server was restarted with reload enabled. Code changes now reach both local instances.

## Verification

- Backend suite: **2,242 passed, 13 skipped, 2 expected failures**.
- Latest targeted backend-pipeline reruns: **9/9 passed**, with the actual answers reviewed for the semantic errors that the original substring checks missed.
- The nine targeted reruns used the database, retrieval, composition, validation and audit pipeline. This is not a fresh run of the entire 59-case HTTP suite, and it does not independently verify frontend rendering.
- Live search and official-page availability remain external dependencies. Missing required source rules do not activate the source-bound explanations.

The answers and audit correlation IDs are in [the targeted verification report](../evals/reports/recurring-failure-fixes-20261008.json).
