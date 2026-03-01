from __future__ import annotations

import os
import random

from dotenv import load_dotenv

load_dotenv()


CONTENT_FLAVORS: dict[str, dict] = {
    "article": {
        "query_template": "{topic} tips guide how to improve",
        "label": "*Read*",
        "intro": "Here's something worth reading:",
    },
    "person": {
        "query_template": "{topic} experts creators to follow",
        "label": "*Follow*",
        "intro": "Someone worth following on this:",
    },
    "podcast": {
        "query_template": "best {topic} podcast episode",
        "label": "*Listen*",
        "intro": "A podcast episode on exactly this:",
    },
    "science": {
        "query_template": "surprising science research behind {topic}",
        "label": "*Did you know*",
        "intro": "Here's a fun fact that might reframe this:",
    },
    "app": {
        "query_template": "best app for {topic} 2024",
        "label": "*Try*",
        "intro": "There's an app that might actually help:",
    },
    "community": {
        "query_template": "{topic} community Reddit Discord forum",
        "label": "*Find your people*",
        "intro": "You're not alone -- there's a community for this:",
    },
    "news": {
        "query_template": "latest {topic} research news 2025",
        "label": "*What's new*",
        "intro": "What's new in this space:",
    },
    "video": {
        "query_template": "{topic} youtube video tutorial",
        "label": "*Watch*",
        "intro": "This video might be worth your time:",
    },
    "trending": {
        "query_template": "{topic} trending news 2025",
        "label": "*Trending*",
        "intro": "Here's what's trending around this:",
    },
    "job": {
        "query_template": "{topic} career jobs opportunities",
        "label": "*Opportunity*",
        "intro": "Something that caught my eye on the opportunity side:",
    },
}

ALL_FLAVORS = list(CONTENT_FLAVORS.keys())


def search_content(query: str, num_results: int = 3) -> list[dict]:
    """Search Exa for relevant content. Returns list of {title, url, snippet, published_date}."""
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        return []

    try:
        import requests

        resp = requests.post(
            "https://api.exa.ai/search",
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "numResults": num_results,
                "type": "auto",
                "contents": {
                    "highlights": {"numSentences": 2},
                },
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("results", []):
            highlights = item.get("highlights") or []
            snippet = highlights[0] if highlights else ""
            results.append({
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": snippet[:300],
                "published_date": item.get("publishedDate") or "",
            })
        return results
    except Exception as e:
        print(f"[exa_client] search failed: {e}")
        return []


def search_content_multi(
    topics: list[str],
    trigger_log: str | None = None,
    count: int = 3,
) -> list[dict]:
    """Return up to `count` Exa results, each with a different flavor.

    `topics` comes from goal.config.domain_topics (LLM-generated per goal).
    Picks random flavors from ALL_FLAVORS.
    Each result: {title, url, snippet, flavor, flavor_label, intro}.
    """
    flavors = random.sample(ALL_FLAVORS, min(count, len(ALL_FLAVORS)))
    seen_urls: set[str] = set()
    results: list[dict] = []

    for i, flavor in enumerate(flavors):
        flavor_config = CONTENT_FLAVORS[flavor]
        topic = topics[i % len(topics)] if topics else "wellness"
        query = flavor_config["query_template"].format(topic=topic)
        if trigger_log:
            query = f"{trigger_log[:60]} {query}"
        hits = search_content(query, num_results=1)
        if not hits:
            continue
        hit = hits[0]
        if hit["url"] in seen_urls:
            continue
        seen_urls.add(hit["url"])
        results.append({
            "title": hit["title"],
            "url": hit["url"],
            "snippet": hit["snippet"],
            "flavor": flavor,
            "flavor_label": flavor_config["label"],
            "intro": flavor_config.get("intro", ""),
        })

    return results
