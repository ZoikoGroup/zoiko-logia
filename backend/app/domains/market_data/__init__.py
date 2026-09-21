"""Market and company data subsystem for Ask Kriton™.

Provider adapters (Companies House, Finnhub, Polygon, Alpha Vantage) behind one
Protocol, with a registry that picks a provider per intent and falls back when
one is unconfigured or unavailable. Mirrors the structure of
app/domains/model_gateway/ — same adapter-behind-a-Protocol shape, same
"first configured provider wins, with fallback" selection — so there is one
pattern in the codebase for talking to third-party providers, not two.

The bridge into the answer pipeline is app/orchestration/market_data.py, which
is deliberately thin: it self-gates, calls this domain, and returns the same
WebSource shape every other live connector returns. Provider-specific code
never leaves this package.
"""
