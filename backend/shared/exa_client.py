from __future__ import annotations

import os
import random

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Content flavors — "Instagram algorithm" for each domain
# ---------------------------------------------------------------------------

CONTENT_FLAVORS: dict[str, dict] = {
    "article": {
        "query_template": "{topic} tips guide how to improve",
        "label": "📖 *Read*",
        "intro": "Here's something worth reading:",
    },
    "person": {
        "query_template": "{topic} experts creators to follow",
        "label": "👤 *Follow*",
        "intro": "Someone worth following on this:",
    },
    "podcast": {
        "query_template": "best {topic} podcast episode",
        "label": "🎙️ *Listen*",
        "intro": "A podcast episode on exactly this:",
    },
    "science": {
        "query_template": "surprising science research behind {topic}",
        "label": "💡 *Did you know*",
        "intro": "Here's a fun fact that might reframe this:",
    },
    "app": {
        "query_template": "best app for {topic} 2024",
        "label": "📱 *Try*",
        "intro": "There's an app that might actually help:",
    },
    "community": {
        "query_template": "{topic} community Reddit Discord forum",
        "label": "🏘️ *Find your people*",
        "intro": "You're not alone — there's a community for this:",
    },
    "news": {
        "query_template": "latest {topic} research news 2025",
        "label": "🆕 *What's new*",
        "intro": "What's new in this space:",
    },
    "video": {
        "query_template": "{topic} youtube video tutorial",
        "label": "🎥 *Watch*",
        "intro": "This video might be worth your time:",
    },
    "trending": {
        "query_template": "{topic} trending news 2025",
        "label": "🔥 *Trending*",
        "intro": "Here's what's trending around this:",
    },
    "job": {
        "query_template": "{topic} career jobs opportunities",
        "label": "💼 *Opportunity*",
        "intro": "Something that caught my eye on the opportunity side:",
    },
}

# Domain-to-topic mappings (used when building Exa queries)
DOMAIN_TOPICS: dict[str, list[str]] = {
    "sleep": ["sleep optimization", "sleep science", "circadian rhythm"],
    "fitness": ["running training", "5K prep", "endurance running"],
    "money": ["personal finance", "budgeting", "financial wellness"],
    "social": ["social wellbeing", "relationships", "loneliness prevention"],
    "short_lived": ["deep work", "productivity under pressure", "focus techniques"],
    "custom": ["deep work", "productivity under pressure", "focus techniques"],
}

# Lighter flavors for nudge-level responses
LIGHT_FLAVORS = ["article", "science", "community"]
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


def search_content_varied(
    topic: str,
    flavor: str | None = None,
    last_flavor: str | None = None,
) -> dict | None:
    """Search Exa with a specific content flavor (single result).

    Returns {title, url, snippet, flavor, flavor_label, intro} or None on failure.
    """
    if not flavor:
        available = [f for f in ALL_FLAVORS if f != last_flavor]
        flavor = random.choice(available) if available else random.choice(ALL_FLAVORS)

    flavor_config = CONTENT_FLAVORS.get(flavor, CONTENT_FLAVORS["article"])
    query = flavor_config["query_template"].format(topic=topic)

    results = search_content(query, num_results=1)
    if not results:
        return None

    r = results[0]
    return {
        "title": r["title"],
        "url": r["url"],
        "snippet": r["snippet"],
        "flavor": flavor,
        "flavor_label": flavor_config["label"],
        "intro": flavor_config.get("intro", ""),
    }


# Flavor sets per template — curated for each domain so we skip the LLM call
TEMPLATE_FLAVOR_SETS: dict[str, list[str]] = {
    "sleep": ["science", "article", "app"],
    "fitness": ["article", "video", "person"],
    "money": ["article", "app", "community"],
    "social": ["community", "podcast", "article"],
    "short_lived": ["article", "video", "person"],
    "custom": ["article", "science", "community"],
}


def search_content_multi(
    topic: str,
    template: str,
    trigger_log: str | None = None,
    count: int = 3,
) -> list[dict]:
    """Return up to `count` Exa results, each with a different flavor.

    Picks flavors from TEMPLATE_FLAVOR_SETS for the given template.
    Each result: {title, url, snippet, flavor, flavor_label, intro}.
    """
    flavors = TEMPLATE_FLAVOR_SETS.get(template, ["article", "science", "community"])[:count]
    seen_urls: set[str] = set()
    results: list[dict] = []

    for flavor in flavors:
        flavor_config = CONTENT_FLAVORS.get(flavor, CONTENT_FLAVORS["article"])
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
