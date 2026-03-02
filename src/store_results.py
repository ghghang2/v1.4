"""
Store harvested results and search data to disk.

The module provides a :func:`save_query_results` function that writes a JSON file
containing the raw search results and harvested metadata.  It also keeps a
``duplicates.json`` file in the results directory to avoid re‑processing the
same URL twice.
"""

import json
import os
import hashlib
import datetime
from pathlib import Path
from typing import List, Dict

# Global variable holding the duplicates set (URL hash -> True)
_DUPLICATES = {}


def _load_duplicates(dup_path: Path):
    if dup_path.is_file():
        with dup_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("hashes", []))
    return set()


def _save_duplicates(dup_path: Path, duplicates: set):
    with dup_path.open("w", encoding="utf-8") as f:
        json.dump({"hashes": list(duplicates)}, f, indent=2)


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def save_query_results(
    query: str,
    raw_search: List[Dict],
    harvested: Dict[str, List[Dict]],
    results_dir: str = "results",
) -> Path:
    """Persist a query run to disk.

    Parameters
    ----------
    query : str
        The original search query.
    raw_search : list of dict
        The raw search results as returned by :func:`search_engine.perform_search`.
    harvested : dict
        Mapping of category (paper, patent, repo, blog) to list of metadata
        dicts harvested from that category.
    results_dir : str, optional
        Directory where the JSON file and duplicates list will be stored.

    Returns
    -------
    pathlib.Path
        Path to the created JSON file.
    """
    path = Path(results_dir)
    path.mkdir(parents=True, exist_ok=True)

    # Load duplicates
    dup_path = path / "duplicates.json"
    duplicates = _load_duplicates(dup_path)

    # Filter out duplicates from raw search
    unique_results = []
    for res in raw_search:
        url = res.get("url")
        if not url:
            continue
        h = _hash_url(url)
        if h in duplicates:
            continue
        duplicates.add(h)
        unique_results.append(res)

    # Update duplicates file
    _save_duplicates(dup_path, duplicates)

    # Prepare payload
    payload = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "query": query,
        "raw_search": unique_results,
        "harvested": harvested,
    }

    # Create filename based on timestamp
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    fname = f"{ts}_{query.replace(' ', '_')}.json"
    out_path = path / fname
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return out_path

# Simple demo
if __name__ == "__main__":
    sample_query = "recursive self‑improvement"
    raw = []  # would be from search engine
    harvested = {"paper": [], "patent": [], "repo": [], "blog": []}
    print("Saving results...")
    print(save_query_results(sample_query, raw, harvested))
