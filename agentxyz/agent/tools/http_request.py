"""Инструмент для выполнения HTTP запросов."""

import json
from typing import Any

import aiohttp

from agentxyz.agent.tools.base import Tool


class HttpRequestTool(Tool):
    """Инструмент для выполнения HTTP запросов с различными методами."""

    def __init__(
        self,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        max_response_size: int = 1_000_000,
        timeout: int = 60,
        user_agent: str = "AgentXYZ/1.0",
    ):
        self._allowed_domains = set(allowed_domains or [])
        self._blocked_domains = set(blocked_domains or [])
        self._max_response_size = max_response_size
        self._timeout = timeout
        self._user_agent = user_agent

    @property
    def name(self) -> str:
        return "http_request"

    @property
    def description(self) -> str:
        return (
            "Make HTTP requests with custom methods, headers, and body. "
            "Supports GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to send the request to",
                },
                "method": {
                    "type": "string",
                    "enum": [
                        "GET",
                        "POST",
                        "PUT",
                        "PATCH",
                        "DELETE",
                        "HEAD",
                        "OPTIONS",
                    ],
                    "description": "HTTP method (default: GET)",
                },
                "headers": {
                    "type": "object",
                    "description": "HTTP headers as key-value pairs",
                },
                "body": {
                    "type": "string",
                    "description": "Request body (for POST, PUT, PATCH)",
                },
                "json_body": {
                    "type": "object",
                    "description": "JSON body as object (auto-sets Content-Type)",
                },
                "request_timeout": {
                    "type": "integer",
                    "description": "Request timeout in seconds (default: from config)",
                },
            },
            "required": ["url"],
        }

    async def execute(  # type: ignore[override]
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
        json_body: dict[str, Any] | None = None,
        request_timeout: int | None = None,
        **kwargs: Any,
    ) -> str:
        # Валидация домена
        domain_error = self._check_domain(url)
        if domain_error:
            return domain_error

        if not url.startswith(("http://", "https://")):
            return "Error: URL must start with http:// or https://"

        method = method.upper()
        if method not in ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]:
            return f"Error: Unsupported HTTP method: {method}"

        # Подготовка заголовков
        request_headers = {"User-Agent": self._user_agent}
        if headers:
            request_headers.update(headers)

        # Подготовка тела запроса
        request_body = None
        content_type_header = None

        if json_body is not None:
            request_body = json.dumps(json_body)
            content_type_header = "application/json"
        elif body is not None:
            request_body = body

        if content_type_header and "Content-Type" not in request_headers:
            request_headers["Content-Type"] = content_type_header

        # Таймаут
        req_timeout = aiohttp.ClientTimeout(total=request_timeout or self._timeout)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    data=request_body,
                    timeout=req_timeout,
                ) as resp:
                    # Сбор информации об ответе
                    status = resp.status
                    response_headers = dict(resp.headers)
                    content_type = response_headers.get(
                        "Content-Type", "application/octet-stream"
                    )

                    # Чтение тела ответа с ограничением размера
                    content = await resp.read()

                    if len(content) > self._max_response_size:
                        content = content[: self._max_response_size]
                        truncated = True
                    else:
                        truncated = False

                    # Декодирование содержимого
                    try:
                        if "application/json" in content_type:
                            body_text = json.dumps(
                                json.loads(content), indent=2, ensure_ascii=False
                            )
                        else:
                            body_text = content.decode("utf-8", errors="replace")
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        body_text = f"<binary data, {len(content)} bytes>"

                    # Формирование результата
                    version = (
                        f"{resp.version[0]}.{resp.version[1]}"
                        if resp.version
                        else "1.1"
                    )
                    result_parts = [
                        f"HTTP/{version} {status} {resp.reason}",
                        f"Content-Type: {content_type}",
                        f"Content-Length: {len(content)}",
                    ]

                    # Добавляем важные заголовки
                    for name in ["Location", "Server", "Date", "Cache-Control", "ETag"]:
                        if name in response_headers:
                            result_parts.append(f"{name}: {response_headers[name]}")

                    result_parts.append("")  # пустая строка
                    result_parts.append(body_text)

                    if truncated:
                        result_parts.append(
                            f"\n[Response truncated to {self._max_response_size} bytes]"
                        )

                    return "\n".join(result_parts)

        except aiohttp.ClientError as e:
            return f"Error: HTTP request failed: {e}"
        except Exception as e:
            return f"Error: {e}"

    def _check_domain(self, url: str) -> str | None:
        """Проверить домен на соответствие правилам доступа."""
        try:
            from urllib.parse import urlparse

            domain = urlparse(url).netloc.lower()

            # Сначала проверяем блокированные домены
            for blocked in self._blocked_domains:
                if domain == blocked or domain.endswith(f".{blocked}"):
                    return f"Error: Domain '{domain}' is blocked"

            # Если есть разрешённые домены, проверяем их
            if self._allowed_domains:
                allowed = any(
                    domain == allowed_domain or domain.endswith(f".{allowed_domain}")
                    for allowed_domain in self._allowed_domains
                )
                if not allowed:
                    return f"Error: Domain '{domain}' is not in allowlist"

            return None

        except Exception:
            return "Error: Invalid URL format"
