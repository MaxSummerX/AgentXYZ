"""Веб-инструменты с fallback: Exa + Tavily + Brave."""

import asyncio
import html
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from ddgs import DDGS
from dotenv import load_dotenv
from exa_py import Exa
from loguru import logger
from readability import Document

from agentxyz.agent.tools.base import Tool


# Загрузить .env файл
load_dotenv(Path.home() / ".agentxyz" / ".env")


# Общие константы
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5


def _validate_url(url: str) -> tuple[bool, str]:
    """Проверить URL: должен быть http(s) имея валидный домен."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


def _strip_tags(text: str) -> str:
    """Удалить HTML-теги и декодировать entities."""

    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """Нормализовать пробелы."""

    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class WebSearchTool(Tool):
    """Умный поиск с fallback по приоритету."""

    def __init__(
        self,
        exa_api_key: str | None = None,
        tavily_api_key: str | None = None,
        brave_api_key: str | None = None,
        max_results: int = 5,
        proxy: str | None = None,
    ):
        self.exa_api_key = exa_api_key or os.environ.get("EXA_API_KEY", "")
        self.tavily_api_key = tavily_api_key or os.environ.get("TAVILY_API_KEY", "")
        self.brave_api_key = brave_api_key or os.environ.get("BRAVE_API_KEY", "")
        self.max_results = max_results
        self.proxy = proxy

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Search the web using Exa, Tavily, DDGS, or Brave. Default: auto (try Exa->Tavily->DDGS->Brave)"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {
                    "type": "integer",
                    "description": "Results (1-10)",
                    "minimum": 1,
                    "maximum": 10,
                },
                "engine": {
                    "type": "string",
                    "enum": ["auto", "exa", "tavily", "ddgs", "brave"],
                    "default": "auto",
                    "description": "Search engine: auto (try Exa->Tavily->DDGS->Brave), exa, tavily, or brave",
                },
            },
            "required": ["query"],
        }

    async def execute(  # type: ignore[override]
        self,
        query: str,
        max_results: int = 5,
        engine: str = "auto",
        **kwargs: Any,
    ) -> str:
        """Выполнить поиск с fallback."""
        if engine == "auto":
            # Пробуем по приоритету
            engines = ["exa", "tavily", "ddgs", "brave"]
        else:
            engines = [engine]

        for eng in engines:
            result = await self._try_search(eng, query, max_results)
            if result:
                return result

        return f"All search engines failed for: {query}"

    async def _try_search(
        self, engine: str, query: str, max_results: int
    ) -> str | None:
        """Попробовать поиск через конкретный движок."""
        key_required = {
            "exa": self.exa_api_key,
            "tavily": self.tavily_api_key,
            "brave": self.brave_api_key,
        }

        if engine in key_required and not key_required[engine]:
            logger.debug("Skipping {}: API key not set", engine)
            return None

        try:
            if engine == "exa":
                return await self._search_exa(query, max_results)
            elif engine == "tavily":
                return await self._search_tavily(query, max_results)
            elif engine == "ddgs":
                return await self._search_ddgs(query, max_results)
            elif engine == "brave":
                return await self._search_brave(query, max_results)
        except Exception as e:
            logger.warning("{} search failed: {}", engine, e)
            return None
        return None

    async def _search_exa(self, query: str, max_results: int) -> str | None:

        exa = Exa(api_key=self.exa_api_key)

        try:
            results = await asyncio.to_thread(
                exa.search,
                query=query,
                type="auto",
                num_results=min(max(max_results, 1), 10),
                contents={"text": {"max_characters": 7500}},  # type: ignore[arg-type]
            )

            if not results.results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, result in enumerate(results.results, 1):
                lines.append(f"{i}. {result.title}\n   {result.url}")
                if hasattr(result, "published_date") and result.published_date:
                    lines.append(f"   📅 {result.published_date}")
                if result.text:
                    # Обрезаем слишком длинный контент
                    text = (
                        result.text[:1000] + "..."
                        if len(result.text) > 1000
                        else result.text
                    )
                    lines.append(f"   {text}")

            return "\n".join(lines)

        except Exception as e:
            return f"Error: {e}"

    async def _search_tavily(self, query: str, max_results: int) -> str:

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                payload = {
                    "query": query,
                    "max_results": min(max(max_results, 1), 10),
                    "search_depth": "basic",
                    "topic": "general",
                }

                response = await client.post(
                    "https://api.tavily.com/search",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.tavily_api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()

                data = response.json()

            if not data.get("results"):
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, result in enumerate(data["results"][:max_results], 1):
                lines.append(
                    f"{i}. {result.get('title', '')}\n   {result.get('url', '')}"
                )
                if content := result.get("content"):
                    # Обрезаем слишком длинный контент
                    text = content[:1000] + "..." if len(content) > 1000 else content
                    lines.append(f"   {text}")

            return "\n".join(lines)

        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    async def _search_ddgs(query: str, max_results: int) -> str | None:
        """Поиск через DuckDuckGo (бесплатно, без ключа)."""
        try:
            # Запускаем синхронный DDGS в потоке, не блокируя event loop
            results: list[dict] = await asyncio.to_thread(
                lambda: DDGS().text(query, max_results=min(max(max_results, 1), 10))
            )

            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results, 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('href', '')}")
                if body := item.get("body"):
                    lines.append(f"   {body}")

            return "\n".join(lines)

        except Exception as e:
            logger.warning("DDGS search failed: {}", e)
            return None

    async def _search_brave(self, query: str, max_results: int, **kwargs: Any) -> str:

        try:
            n = min(max(max_results or self.max_results, 1), 10)
            logger.debug(
                "WebSearch: {}", "прокси включён" if self.proxy else "прямое соединение"
            )
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": self.brave_api_key,
                    },
                    timeout=10.0,
                )
                r.raise_for_status()

            results = r.json().get("web", {}).get("results", [])[:n]
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return "\n".join(lines)
        except httpx.ProxyError as e:
            logger.error("Ошибка прокси WebSearch: {}", e)
            return f"Proxy error: {e}"
        except Exception as e:
            logger.error("Ошибка WebSearch: {}", e)
            return f"Error: {e}"


class WebFetchTool(Tool):
    """Универсальное извлечение контента с fallback: Tavily → Exa → Readability."""

    def __init__(
        self,
        tavily_api_key: str | None = None,
        exa_api_key: str | None = None,
        max_chars: int = 50000,
        accept_markdown: bool = False,
        proxy: str | None = None,
    ):
        self.tavily_api_key = tavily_api_key or os.environ.get("TAVILY_API_KEY", "")
        self.exa_api_key = exa_api_key or os.environ.get("EXA_API_KEY", "")
        self.max_chars = max_chars
        self.accept_markdown = accept_markdown
        self.proxy = proxy

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return "Extract content from URLs. Tries Tavily → Exa → Readability."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "extract_mode": {
                    "type": "string",
                    "enum": ["markdown", "text"],
                    "default": "markdown",
                },
                "max_chars": {"type": "integer", "minimum": 100},
                "accept_markdown": {
                    "type": "boolean",
                    "default": False,
                    "description": "Request text/markdown from Cloudflare and other compatible sites",
                },
            },
            "required": ["url"],
        }

    async def execute(  # type: ignore[override]
        self,
        url: str,
        extract_mode: str = "markdown",
        max_chars: int | None = None,
        proxy: str | None = None,
        accept_markdown: bool | None = None,
        **kwargs: Any,
    ) -> str:
        """Извлечь контент с fallback: Tavily → Exa → Readability."""
        max_chars = max_chars or self.max_chars

        effective_accept_markdown = (
            accept_markdown if accept_markdown is not None else self.accept_markdown
        )

        # Проверить URL
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps(
                {"error": f"URL validation failed: {error_msg}", "url": url},
                ensure_ascii=False,
            )

        # 1. Пробуем Tavily Extract
        if self.tavily_api_key:
            tavily_result = await self._try_tavily_extract(url, extract_mode, max_chars)
            if tavily_result:
                return tavily_result

        # 2. Пробуем Exa Contents
        if self.exa_api_key:
            exa_result = await self._try_exa_contents(url, max_chars)
            if exa_result:
                return exa_result

        # 3. Fallback на Readability
        return await self._extract_readability(
            url, extract_mode, max_chars, effective_accept_markdown
        )

    async def _try_tavily_extract(
        self, url: str, extract_mode: str, max_chars: int
    ) -> str | None:
        """Попробовать извлечь через Tavily."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                payload = {
                    "urls": [url],
                    "extract_depth": "advanced"
                    if extract_mode == "markdown"
                    else "basic",
                    "format": extract_mode,
                }

                response = await client.post(
                    "https://api.tavily.com/extract",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.tavily_api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()

                data = response.json()

            if data.get("results"):
                result = data["results"][0]
                text = result.get("raw_content", "")
                truncated = len(text) > max_chars
                if truncated:
                    text = text[:max_chars]

                return json.dumps(
                    {
                        "url": url,
                        "status": response.status_code,
                        "extractor": "tavily",
                        "truncated": truncated,
                        "length": len(text),
                        "text": text,
                    }
                )
        except Exception as e:
            logger.warning("Tavily extract failed: {}", e)
        return None

    async def _try_exa_contents(self, url: str, max_chars: int) -> str | None:
        """Попробовать извлечь через Exa Contents API."""

        try:
            exa = Exa(api_key=self.exa_api_key)

            contents_result = await asyncio.to_thread(
                exa.get_contents,  # type: ignore[arg-type]
                urls=[url],
                text={"max_characters": max_chars},
            )

            if (
                contents_result
                and hasattr(contents_result, "results")
                and contents_result.results
            ):
                result = contents_result.results[0]
                text = getattr(result, "text", "")

                if not text:
                    return None

                title = getattr(result, "title", "")
                author = getattr(result, "author", "")
                published_date = getattr(result, "publishedDate", "")

                metadata = {}
                if title:
                    metadata["title"] = title
                if author:
                    metadata["author"] = author
                if published_date:
                    metadata["published_date"] = published_date

                return json.dumps(
                    {
                        "url": url,
                        "status": 200,
                        "extractor": "exa",
                        "length": len(text),
                        "text": text,
                        **metadata,
                    }
                )
        except Exception as e:
            logger.warning("Exa contents failed: {}", e)
        return None

    async def _extract_readability(
        self, url: str, extract_mode: str, max_chars: int, accept_markdown: bool | None
    ) -> str:
        """Извлечь через Readability (fallback)."""
        max_chars = max_chars or self.max_chars
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps(
                {"error": f"URL validation failed: {error_msg}", "url": url},
                ensure_ascii=False,
            )

        try:
            headers = {"User-Agent": USER_AGENT}
            logger.debug(
                "WebFetch: {}", "прокси включён" if self.proxy else "прямое соединение"
            )
            if accept_markdown:
                headers["Accept"] = "text/markdown, text/html, */*"

            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=30.0,
                proxy=self.proxy,
            ) as client:
                r = await client.get(url, headers=headers)
                r.raise_for_status()

            ctype = r.headers.get("content-type", "")

            # Новые заголовки для агента
            markdown_tokens = r.headers.get("x-markdown-tokens")
            content_signal = r.headers.get("content-signal")

            # JSON
            if "application/json" in ctype:
                text, extractor = (
                    json.dumps(r.json(), indent=2, ensure_ascii=False),
                    "json",
                )
            # Markdown
            elif "text/markdown" in ctype:
                text, extractor = r.text, "markdown"
            # HTML
            elif "text/html" in ctype or r.text[:256].lower().startswith(
                ("<!doctype", "<html")
            ):
                doc = Document(r.text)
                content = (
                    self._to_markdown(doc.summary())
                    if extract_mode == "markdown"
                    else _strip_tags(doc.summary())
                )
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            else:
                text, extractor = r.text, "raw"

            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            result = {
                "url": url,
                "finalUrl": str(r.url),
                "status": r.status_code,
                "extractor": extractor,
                "truncated": truncated,
                "length": len(text),
                "text": text,
            }

            # Добавляем markdown-метаданные, если есть
            if markdown_tokens:
                result["markdown_tokens"] = markdown_tokens
            if content_signal:
                result["content_signal"] = content_signal
            return json.dumps(result, ensure_ascii=False)

        except httpx.ProxyError as e:
            logger.error("Ошибка прокси WebFetch для {}: {}", url, e)
            return json.dumps(
                {"error": f"Proxy error: {e}", "url": url}, ensure_ascii=False
            )
        except Exception as e:
            logger.error("Ошибка WebFetch для {}: {}", url, e)
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)

    @staticmethod
    def _to_markdown(html_code: str) -> str:
        """Конвертировать HTML в markdown."""

        # Конвертировать ссылки, заголовки, перечни перед удалением тегов
        text = re.sub(
            r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
            lambda m: f"[{_strip_tags(m[2])}]({m[1]})",
            html_code,
            flags=re.I,
        )
        text = re.sub(
            r"<h([1-6])[^>]*>([\s\S]*?)</h\1>",
            lambda m: f"\n{'#' * int(m[1])} {_strip_tags(m[2])}\n",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"<li[^>]*>([\s\S]*?)</li>",
            lambda m: f"\n- {_strip_tags(m[1])}",
            text,
            flags=re.I,
        )
        text = re.sub(r"</(p|div|section|article)>", "\n\n", text, flags=re.I)
        text = re.sub(r"<(br|hr)\s*/?>", "\n", text, flags=re.I)
        return _normalize(_strip_tags(text))
