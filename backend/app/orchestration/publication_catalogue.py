"""Verified public downloads for publication pages that may block readers.

Entries describe documents, not answers or question patterns. They are used
only when retrieval already selected that exact publication. Download URLs
were checked against the publisher's own download link on 27 October 2026.
"""
from urllib.parse import urlsplit


PUBLICATION_DOWNLOADS = {
    "https://www.oecd.org/en/publications/oecd-transfer-pricing-guidelines-for-multinational-enterprises-and-tax-administrations-2022_0e655865-en.html":
        "https://www.oecd.org/content/dam/oecd/en/publications/reports/2022/01/oecd-transfer-pricing-guidelines-for-multinational-enterprises-and-tax-administrations-2022_57104b3a/0e655865-en.pdf",
}


def known_publication_download(url: str) -> str | None:
    def key(value: str):
        parsed = urlsplit(value)
        return (parsed.hostname or "").removeprefix("www."), parsed.path.rstrip("/")

    return next((document for page, document in PUBLICATION_DOWNLOADS.items() if key(page) == key(url)), None)
