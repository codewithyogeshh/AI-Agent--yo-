"""Web research tools: search, fetch, cited report.

Search uses DuckDuckGo's public HTML endpoint (no key required). Every tool
degrades honestly: if the network or the endpoint fails, the result says so.
Content pulled from the web is untrusted data and is never executed.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import ToolContext, ToolResult, tool

USER_AGENT = "NOVA-Agent/1.0 (+personal assistant; research bot)"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
BLOCK_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "system prompt",
    "you are now",
    "disregard the above",
)


def _clean_url(href: str) -> str:
    if href.startswith("//duckduckgo.com/l/"):
        query = parse_qs(urlparse("https:" + href).query)
        raw = query.get("uddg", [""])[0]
        return unquote(raw)
    return href


def _sanitize(text: str, limit: int = 8000) -> str:
    """Strip obvious prompt-injection cues from external text before it reaches the agent."""
    lines = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in BLOCK_MARKERS):
            continue
        lines.append(line)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return cleaned[:limit]


async def duckduckgo_search(query: str, limit: int = 6) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=HEADERS) as client:
        res = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        for node in soup.select("div.result"):
            link = node.select_one("a.result__a")
            if not link:
                continue
            href = _clean_url(link.get("href", ""))
            if not href.startswith("http"):
                continue
            snippet = node.select_one(".result__snippet")
            results.append(
                {
                    "title": link.get_text(" ", strip=True)[:200],
                    "url": href,
                    "snippet": _sanitize(snippet.get_text(" ", strip=True), 400) if snippet else "",
                }
            )
            if len(results) >= limit:
                break
    return results


async def fetch_readable(url: str, max_chars: int = 6000) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=HEADERS) as client:
        res = await client.get(url)
        res.raise_for_status()
        content_type = res.headers.get("content-type", "")
        if "pdf" in content_type:
            return {"url": url, "title": url, "text": "", "note": "PDF fetched; text extraction needs an OCR/PDF tool."}
        soup = BeautifulSoup(res.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "footer", "aside", "form"]):
            tag.decompose()
        title = (soup.title.get_text(strip=True) if soup.title else url)[:200]
        article = soup.find("article") or soup.find("main") or soup.body or soup
        text = _sanitize(article.get_text("\n", strip=True), max_chars)
        return {"url": url, "title": title, "text": text}


@tool(
    name="web.search",
    description="Search the public web and return ranked titles, URLs and snippets.",
    category="research",
    params={
        "query": {"type": "string", "required": True, "description": "Search query"},
        "limit": {"type": "integer", "required": False, "description": "Max results (default 6)"},
    },
)
async def web_search(ctx: ToolContext, query: str, limit: int = 6) -> ToolResult:
    ctx.emit("tool", f"Searching the web for “{query}”", {"query": query})
    try:
        results = await duckduckgo_search(query, min(int(limit), 10))
    except Exception as exc:  # network / endpoint failures are reported, never hidden
        return ToolResult(False, f"Web search failed: {exc}", verified=False)
    if not results:
        return ToolResult(False, "No search results returned. The search endpoint may be rate limited.", {"query": query}, verified=False)
    lines = [f"{i + 1}. {r['title']} — {r['url']}" for i, r in enumerate(results)]
    return ToolResult(
        True,
        f"Found {len(results)} sources for “{query}”",
        {"query": query, "results": results},
        artifacts=[
            {
                "kind": "link",
                "title": r["title"][:80],
                "url": r["url"],
            }
            for r in results
        ],
    )


@tool(
    name="web.fetch",
    description="Fetch a web page and return its readable text (untrusted data).",
    category="research",
    params={
        "url": {"type": "string", "required": True, "description": "Absolute http(s) URL"},
        "max_chars": {"type": "integer", "required": False, "description": "Text cap (default 6000)"},
    },
)
async def web_fetch(ctx: ToolContext, url: str, max_chars: int = 6000) -> ToolResult:
    if not url.startswith(("http://", "https://")):
        return ToolResult(False, "Only absolute http(s) URLs are allowed", verified=False)
    try:
        page = await fetch_readable(url, max_chars)
    except Exception as exc:
        return ToolResult(False, f"Fetch failed for {url}: {exc}", verified=False)
    if len(page["text"]) < 80:
        return ToolResult(False, f"Page yielded too little text: {url}", page, verified=False)
    return ToolResult(True, f"Fetched {len(page['text'])} characters from {page['title'][:80]}", page)


@tool(
    name="research.report",
    description="Search several sources, extract their content and write a cited research report to the workspace.",
    category="research",
    params={
        "topic": {"type": "string", "required": True},
        "max_sources": {"type": "integer", "required": False},
        "angle": {"type": "string", "required": False, "description": "Optional focus or audience"},
    },
)
async def research_report(ctx: ToolContext, topic: str, max_sources: int = 4, angle: str = "") -> ToolResult:
    from ..agent import llm

    ctx.emit("tool", f"Building a research report on “{topic}”", {"topic": topic})
    queries = [topic, f"{topic} latest developments", f"{topic} analysis"]
    found: List[Dict[str, str]] = []
    seen = set()
    for query in queries:
        try:
            for item in await duckduckgo_search(query, 5):
                if item["url"] in seen:
                    continue
                seen.add(item["url"])
                found.append(item)
        except Exception:
            continue
        if len(found) >= max_sources + 3:
            break

    if not found:
        return ToolResult(
            False,
            "Could not reach a search provider. Check outbound network access and retry.",
            verified=False,
        )

    pages: List[Dict[str, Any]] = []
    for item in found[: max(1, int(max_sources))]:
        try:
            page = await fetch_readable(item["url"], 3500)
            if page["text"]:
                pages.append(page)
        except Exception:
            continue
        await asyncio.sleep(0.2)

    sources_md = "\n".join(
        f"- [{p['title'] or p['url']}]({p['url']})" for p in (pages or [{"title": f["title"], "url": f["url"]} for f in found[:6]])
    )
    digest = "\n\n".join(
        f"### {p['title']}\n{p['url']}\n\n{p['text'][:1200]}" for p in pages
    ) or "\n".join(f"### {f['title']}\n{f['url']}\n\n{f['snippet']}" for f in found[:6])

    summary = ""
    provider_note = "Extractive digest — no AI provider configured, so excerpts are quoted rather than rewritten."
    if llm.active_provider():
        result = await llm.complete_optional(
            (
                f"Write a practical research brief on: {topic}\nFocus: {angle or 'general audience, actionable'}\n"
                "Use only the sources below. Include: 1) Key findings (bulleted, with source numbers), "
                "2) What is genuinely new, 3) Risks or open questions, 4) Three concrete next actions. "
                "Be factual and concise. Do not invent facts.\n\nSOURCES:\n"
                + "\n\n".join(f"[{i + 1}] {p['title']} ({p['url']})\n{p['text'][:2500]}" for i, p in enumerate(pages or found[:6]))
            ),
            temperature=0.3,
            max_tokens=1600,
        )
        if result is not None:
            summary = result.text
            provider_note = f"Summarised by {result.provider} ({result.model}) from {len(pages) or len(found)} sources."

    body = (
        f"# Research brief: {topic}\n\n"
        f"Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z\n\n"
        f"{summary or '_Summary unavailable — see source excerpts below._'}\n\n"
        "## Sources\n\n"
        f"{sources_md}\n\n"
        f"## Source excerpts\n\n{digest}\n\n"
        f"---\n_{provider_note}_\n"
    )

    reports_dir = ctx.user_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower())[:48].strip("-") or "report"
    path = reports_dir / f"{datetime.utcnow():%Y%m%d-%H%M%S}-{slug}.md"
    path.write_text(body, encoding="utf-8")

    return ToolResult(
        True,
        f"Research report written: {path.name} ({len(pages) or len(found)} sources)",
        {
            "path": str(path),
            "sources": [{"title": p["title"], "url": p["url"]} for p in (pages or found[:6])],
            "summary": (summary or "")[:4000],
        },
        verified=bool(pages),
        artifacts=[{"kind": "report", "title": f"Research: {topic}", "path": str(path)}],
    )


@tool(
    name="system.status",
    description="Report the live status of NOVA subsystems and configured integrations.",
    category="system",
    params={},
)
async def system_status(ctx: ToolContext) -> ToolResult:
    from ..agent.llm import capabilities
    from ..services.integration_registry import integration_status

    caps = capabilities()
    integrations = integration_status(ctx.db, ctx.user)
    connected = [i["provider"] for i in integrations if i["status"] == "connected"]
    return ToolResult(
        True,
        f"AI: {caps['provider']} · Connected integrations: {len(connected)}",
        {"ai": caps, "integrations": integrations},
    )
