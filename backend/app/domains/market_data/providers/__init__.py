"""Provider adapters. Each one converts a single vendor's API into the
normalized models in ../schemas.py and raises the typed errors defined there.
Nothing outside this package may import a vendor SDK or hard-code a vendor URL.
"""
