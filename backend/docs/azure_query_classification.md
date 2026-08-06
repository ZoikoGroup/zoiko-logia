# Azure AI Search query classification

Kriton can optionally use an Azure AI Search index to classify queries that
do not match an explicit deterministic rule. Azure proposes a retrieval
category only. Security screening, source licensing, professional-risk
classification, and route selection remain local deterministic controls.

## Rollout modes

- `off`: current deterministic and local-embedding behavior only.
- `shadow`: query Azure and audit its proposed category without changing the route.
- `fallback`: accept a clear Azure winner before trying the local embedding fallback.

Start with `shadow`, evaluate labelled traffic, then enable `fallback` after
category-specific accuracy and confusion thresholds pass review.

## Classification index

Create an Azure AI Search index whose documents represent approved query
classes. The runtime requires these retrievable fields:

- `classification_id` (`Edm.String`, key)
- `category` (`Edm.String`, filterable)
- `example_text` (`Edm.String`, searchable)

For semantic ranking, create a semantic configuration that uses
`example_text` as its content field. For hybrid vector classification, add:

- `example_vector` (`Collection(Edm.Single)`, searchable) with a configured vectorizer

Then set `AZURE_AI_SEARCH_CLASSIFICATION_VECTOR_FIELD=example_vector`.
Leave this setting empty when the index has no query-time vectorizer; the
adapter will use keyword plus semantic ranking instead.

Example document:

```json
{
  "classification_id": "audit-variance-testing-1",
  "category": "accounting-fundamentals",
  "example_text": "Does an unexplained account variance require additional audit testing?"
}
```

Store several independently reviewed examples for each category. Do not place
security or final professional-risk outcomes in this index because those are
policy decisions, not search classifications.

## Acceptance thresholds

`@search.rerankerScore` and `@search.score` are relevance scores, not
probabilities. Tune `MIN_SCORE` and `MIN_MARGIN` against a labelled Kriton
evaluation set. A result is accepted only when the first result clears the
minimum score and leads the second result by the configured margin. Otherwise,
Kriton uses its existing local fallback.

Every orchestration decision emits `query_classified` with the chosen category,
method, scores, classification document ID, and shadow proposal where relevant.
API keys and query content are not included in this audit event.
