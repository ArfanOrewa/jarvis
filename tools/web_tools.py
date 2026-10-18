"""
web_tools.py — Keyless web tools for the Jarvis voice assistant.

Tools (all return str, never raise):
    web_search   DuckDuckGo text search (ddgs), keyless.
    web_fetch    Extract article text from a URL (trafilatura), keyless.
    wikipedia    Wikipedia REST summary for a topic, keyless.
    get_news     Google News RSS headlines, keyless.
    get_weather  Open-Meteo geocode + forecast, keyless.

Each module-level function is registered in FUNCS and described in SCHEMAS
(OpenAI function-calling format).
"""

import urllib.parse

import requests

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Searches the web for the given query using DuckDuckGo. "
                "Returns a numbered list of results with title, snippet and URL. "
                "Use this when the user asks about current events, facts you are unsure of, "
                "or anything that needs up-to-date information from the internet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "How many results to return (default 5).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetches a web page and extracts its main article text. "
                "Use this when the user asks you to read a link, open an article, or "
                "get details from a specific URL that a search result only summarized."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL of the page to fetch.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters of extracted text (default 4000).",
                        "default": 4000,
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wikipedia",
            "description": (
                "Looks up a topic on Wikipedia and returns its summary. "
                "Use this for background knowledge questions about people, places, "
                "concepts, or history where a concise encyclopedia summary is ideal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic or article title to look up.",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": (
                "Gets current news headlines from Google News RSS. "
                "Use this when the user asks for the latest news, news about a topic, "
                "or what is happening in the world right now."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional topic to search for; empty returns top headlines.",
                        "default": "",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "How many headlines to return (default 5).",
                        "default": 5,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "Gets the current weather for a city using Open-Meteo. "
                "Use this whenever the user asks about the weather, temperature, "
                "or conditions somewhere — now or for planning."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. 'Bengaluru' or 'New York'.",
                    },
                },
                "required": ["city"],
            },
        },
    },
]


def web_search(query, max_results=5):
    """DuckDuckGo text search via the ddgs package."""
    try:
        from ddgs import DDGS

        max_results = max(1, min(int(max_results), 20))
        with DDGS() as d:
            results = list(d.text(str(query), max_results=max_results))
        if not results:
            return "No search results found."
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            url = r.get("href", "")
            body = (r.get("body", "") or "").replace("\n", " ").strip()
            lines.append(f"{i}. {title} — {body} ({url})")
        return "\n".join(lines)
    except Exception as e:
        return f"web_search error: {e}"


def web_fetch(url, max_chars=4000):
    """Extract the main article text from a URL using trafilatura."""
    try:
        from trafilatura import fetch_url, extract

        downloaded = fetch_url(str(url))
        if not downloaded:
            return f"Could not download the page: {url}"
        text = extract(downloaded, include_comments=False) or ""
        text = text.strip()
        if not text:
            return f"No readable article text found at {url}."
        return text[: max(1, int(max_chars))]
    except Exception as e:
        return f"web_fetch error: {e}"


def wikipedia(topic):
    """Wikipedia REST API page summary."""
    try:
        slug = urllib.parse.quote(str(topic).strip().replace(" ", "_"))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}"
        headers = {
            "User-Agent": "JarvisVoiceAssistant/1.0 (educational personal project)"
        }
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 404:
            return f"No Wikipedia article found for '{topic}'."
        r.raise_for_status()
        data = r.json()
        title = data.get("title", topic)
        extract_text = data.get("extract", "")
        page_url = (
            data.get("content_urls", {}).get("desktop", {}).get("page", "")
        )
        if not extract_text:
            return f"Wikipedia article '{title}' found but has no summary text."
        return f"{title}\n{extract_text}\n{page_url}"
    except Exception as e:
        return f"wikipedia error: {e}"


def get_news(query="", max_results=5):
    """Google News RSS headlines (top news or topic search)."""
    try:
        import feedparser

        query = str(query).strip()
        if query:
            feed_url = (
                "https://news.google.com/rss/search?q="
                + urllib.parse.quote(query)
            )
        else:
            feed_url = "https://news.google.com/rss"
        feed = feedparser.parse(feed_url)
        entries = feed.get("entries", []) if isinstance(feed, dict) else feed.entries
        if not entries:
            return "No news headlines found."
        max_results = max(1, min(int(max_results), 20))
        lines = []
        for e in entries[:max_results]:
            title = e.get("title", "Untitled")
            source = e.get("source", {}).get("title", "") if isinstance(
                e.get("source"), dict
            ) else ""
            published = e.get("published", "")
            detail = ", ".join(p for p in (source, published) if p)
            lines.append(f"- {title} ({detail})" if detail else f"- {title}")
        return "\n".join(lines)
    except Exception as e:
        return f"get_news error: {e}"


_WEATHER_CODES = [
    (lambda c: c == 0, "Clear"),
    (lambda c: 1 <= c <= 3, "Partly cloudy"),
    (lambda c: c in (45, 48), "Fog"),
    (lambda c: 51 <= c <= 55, "Drizzle"),
    (lambda c: 56 <= c <= 57, "Freezing drizzle"),
    (lambda c: 61 <= c <= 65, "Rain"),
    (lambda c: 66 <= c <= 67, "Freezing rain"),
    (lambda c: 71 <= c <= 77, "Snow"),
    (lambda c: 80 <= c <= 82, "Showers"),
    (lambda c: 85 <= c <= 86, "Snow showers"),
    (lambda c: 95 <= c <= 99, "Thunderstorm"),
]


def _weather_desc(code):
    for pred, desc in _WEATHER_CODES:
        if pred(code):
            return desc
    return "Unknown"


def get_weather(city):
    """Current weather via Open-Meteo (geocode + forecast)."""
    try:
        city = str(city).strip()
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1},
            timeout=15,
        )
        geo.raise_for_status()
        places = geo.json().get("results", [])
        if not places:
            return f"City not found: {city}"
        place = places[0]
        lat, lon = place["latitude"], place["longitude"]
        name = place.get("name", city)
        country = place.get("country", "")
        wx = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=15,
        )
        wx.raise_for_status()
        cur = wx.json().get("current", {})
        temp = cur.get("temperature_2m")
        humidity = cur.get("relative_humidity_2m")
        code = cur.get("weather_code", -1)
        wind = cur.get("wind_speed_10m")
        location = f"{name}, {country}".rstrip(", ")
        return (
            f"{location}: {_weather_desc(code)} — {temp}°C, "
            f"humidity {humidity}%, wind {wind} km/h"
        )
    except Exception as e:
        return f"get_weather error: {e}"


FUNCS = {
    "web_search": web_search,
    "web_fetch": web_fetch,
    "wikipedia": wikipedia,
    "get_news": get_news,
    "get_weather": get_weather,
}


if __name__ == "__main__":
    print("== web_search ==")
    print(web_search("python requests library", max_results=2)[:500])
    print("\n== web_fetch ==")
    print(web_fetch("https://example.com", max_chars=500))
    print("\n== wikipedia ==")
    print(wikipedia("Python (programming language)")[:500])
    print("\n== get_news ==")
    print(get_news("", max_results=3))
    print("\n== get_weather ==")
    print(get_weather("Bengaluru"))
