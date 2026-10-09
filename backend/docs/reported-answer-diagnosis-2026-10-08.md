# Reported responses and recurring failures — 8 October 2026

## Attachment assessment

CGST/SGST, Singapore, UAE and the UK VAT threshold responses supplied in the attachment were sufficient for their questions. Five other responses failed:

| Request | Failure |
| --- | --- |
| Three numbered calculations | Dropped current/quick ratios and CAGR; borrowed another question's liabilities and returned debt/equity 0.5 instead of 1.5. |
| Malaysia GST replacement | Dropped SST and confused zero-rating in June with the subsequent transition. |
| Two UK corporation-tax scenarios | Removed the £40,000 scenario while still presenting a complete answer. |
| India registration | Omitted compulsory categories and service exemptions; volunteered unsupported historical statements. |
| Bangalore service exports | Missing statutory export conditions, blanket IEC requirement and confusion between refunds of IGST paid and unused input tax credit. |

## Causes and changes

The previous regression prompts differed from the user's actual questions. The batch parser did not support plural “ratios” or “three years”; when it failed, the whole-message parser incorrectly combined unrelated inputs. Numbered inputs now stay isolated, supported year words normalize before calculation, and unsupported/nonconsecutive batches cannot fall back to a single calculation.

Verification checked individual claims without consistently checking the completeness of the surviving answer. Requested-topic coverage now triggers an evidence-bound correction, runs after pruning, and marks any remaining gaps as incomplete. A newly incomplete pruned answer receives one bounded repair attempt, subject to factual, arithmetic and chart checks. Incomplete requested-topic coverage also prevents feedback learning from caching that answer.

Source coverage missed the statute behind the requested conditions. Source retrieval now includes the HMRC profit-band page, India Code registration provisions, the IGST definition and its official amendment. Selected statutory passages remain contiguous. Indexed Malaysian transition PDFs returned 404; the working Customs FAQ provides explicit repeal and SST transition evidence. Narrow source-backed summaries require the actual retrieved rules and citations, and fail closed when required passages are unavailable. No governed-library ingestion permissions were bypassed.

Checks now reject an ordinary/non-ring-fence company's special ring-fence rate, an IGST-paid refund attached to an unpaid-IGST invoice, and blanket inter-state service registration without exemptions. Source-grounded registration includes statutory categories plus exemption context; export guidance requires all five qualification conditions and evidence for RBI-permitted rupee receipts when those conditions are requested.

## Verification

The exact numbered question returns current ratio 2.5, quick ratio 2, debt/equity 1.5 and CAGR 14.47%. Added regressions cover unsupported batches, missing comparison rows, incomplete statutory passages, export conditions, refund confusion and improper feedback learning.

The exact Malaysia, corporation-tax, India-registration and Bangalore-export questions completed live orchestration checks. Their texts and audit correlation IDs are in `../evals/reports/reported-answer-fixes-20261008.json`. These exercise the backend with its database and source/model providers; they do not prove every future formulation or browser interaction. An extra repeat was not executed because automatic approval review hit an account usage limit.

## Feedback buttons and no-feedback behavior

The feedback endpoint waits for rating storage, audit writes and verified-learning checks. The UI previously showed no thumbs-up progress and displayed the negative-reason form while submitting a positive vote. It now shows immediate saving progress, locks duplicate submissions and displays the reason form only for a negative vote. Server confirmation still waits for the backend; no latency benchmark was available.

No feedback is not approval. Ordinary answers still undergo retrieval, calculation, validation and audit recording. The training collector excludes unrated answers unless they are separately eligible verified corrections. Upvotes can retain verified, complete answers; downvotes can initiate a verified background correction. Clicking feedback does not directly retrain model weights. Training and the bounded arithmetic RL workflow run separately.
