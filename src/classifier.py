"""
Simple domain‑based classifier.

Given a URL, we inspect the domain (or a few key path patterns) to
categorise the resource as one of the following types:

- ``paper``
- ``patent``
- ``repo``
- ``blog``
- ``unknown``

This is intentionally lightweight; it can be extended with more
regexes or a ML‑based classifier later.
"""

import re
from urllib.parse import urlparse

# Ordered list of patterns to match – first match wins.
PATTERNS = [
    (re.compile(r"arxiv\.org"), "paper"),
    (re.compile(r"semanticscholar\.org"), "paper"),
    (re.compile(r"crossref\.org"), "paper"),
    (re.compile(r"patents\.google\.com"), "patent"),
    (re.compile(r"uspto\.gov"), "patent"),
    (re.compile(r"github\.com"), "repo"),
    (re.compile(r"gitlab\.com"), "repo"),
    (re.compile(r"bitbucket\.org"), "repo"),
    (re.compile(r"medium\.com"), "blog"),
    (re.compile(r"towardsdatascience\.com"), "blog"),
    (re.compile(r"dev\.to"), "blog"),
]


def classify_url(url: str) -> str:
    """Return a high‑level type for the given URL.

    Parameters
    ----------
    url: str
        The URL to classify.

    Returns
    -------
    str
        One of ``paper``, ``patent``, ``repo``, ``blog`` or ``unknown``.
    """
    domain = urlparse(url).netloc.lower()
    for pattern, t in PATTERNS:
        if pattern.search(domain):
            return t
    return "unknown"

# Simple test harness – can be replaced by proper unit tests.
if __name__ == "__main__":
    test = [
        "https://arxiv.org/abs/2305.00001",
        "https://patents.google.com/patent/US1234567A",
        "https://github.com/openai/gpt-3",
        "https://medium.com/@someuser/some-article",
        "https://example.com/page",
    ]
    for u in test:
        print(u, "->", classify_url(u))
