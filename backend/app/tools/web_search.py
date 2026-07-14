"""Herramienta web_search: búsqueda vía DuckDuckGo HTML (sin API key)."""

import html
import re
import urllib.parse

import httpx

from app.tools.base import Tool, ToolContext, ToolError

_RESULT_RE = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet>.*?)</a>', re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(fragment: str) -> str:
    return html.unescape(_TAG_RE.sub("", fragment)).strip()


def _real_url(href: str) -> str:
    # DuckDuckGo envuelve las URLs: //duckduckgo.com/l/?uddg=<url-encoded>
    if "uddg=" in href:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if qs.get("uddg"):
            return qs["uddg"][0]
    return href


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Busca en la web y devuelve los títulos, URLs y fragmentos de los mejores resultados. "
        "Úsala cuando necesites información actual o fuentes externas."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Texto de búsqueda"},
            "max_results": {
                "type": "integer",
                "description": "Máximo de resultados (default 5, máx 10)",
            },
        },
        "required": ["query"],
    }
    risk_level = "safe"
    timeout_seconds = 30

    async def run(self, args: dict, ctx: ToolContext) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            raise ToolError("El argumento 'query' es obligatorio y no puede estar vacío")
        max_results = min(int(args.get("max_results") or 5), 10)

        try:
            async with httpx.AsyncClient(
                timeout=20, follow_redirects=True, headers={"User-Agent": "AgentForge/0.1"}
            ) as client:
                response = await client.post(
                    "https://html.duckduckgo.com/html/", data={"q": query}
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ToolError(f"Fallo de red en la búsqueda: {exc}") from exc

        body = response.text
        titles = list(_RESULT_RE.finditer(body))
        snippets = [_clean(m.group("snippet")) for m in _SNIPPET_RE.finditer(body)]

        if not titles:
            return f"Sin resultados para: {query}"

        lines = []
        for i, match in enumerate(titles[:max_results]):
            title = _clean(match.group("title"))
            url = _real_url(html.unescape(match.group("href")))
            snippet = snippets[i] if i < len(snippets) else ""
            lines.append(f"{i + 1}. {title}\n   {url}\n   {snippet}")
        return "\n".join(lines)
