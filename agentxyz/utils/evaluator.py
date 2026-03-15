"""Оценка после выполнения для фоновых задач (heartbeat & cron).

После выполнения агентом фоновой задачи этот модуль делает легковесный
вызов LLM для определения того, стоит ли уведомлять пользователя о результате.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger


if TYPE_CHECKING:
    from agentxyz.providers.base import LLMProvider

_EVALUATE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_notification",
            "description": "Decide whether the user should be notified about this background task result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "should_notify": {
                        "type": "boolean",
                        "description": "true = result contains actionable/important info the user should see; false = routine or empty, safe to suppress",
                    },
                    "reason": {
                        "type": "string",
                        "description": "One-sentence reason for the decision",
                    },
                },
                "required": ["should_notify"],
            },
        },
    }
]

_SYSTEM_PROMPT = (
    "You are a notification gate for a background agent. "
    "You will be given the original task and the agent's response. "
    "Call the evaluate_notification tool to decide whether the user "
    "should be notified.\n\n"
    "Notify when the response contains actionable information, errors, "
    "completed deliverables, or anything the user explicitly asked to "
    "be reminded about.\n\n"
    "Suppress when the response is a routine status check with nothing "
    "new, a confirmation that everything is normal, or essentially empty."
)


async def evaluate_response(
    response: str,
    task_context: str,
    provider: LLMProvider,
    model: str,
) -> bool:
    """Определить, стоит ли доставлять пользователю результат фоновой задачи.

    Использует легковесный запрос LLM с вызовом инструмента (тот же паттерн,
    что heartbeat ``_decide()``). При любой ошибке возвращает ``True``
    (уведомить), чтобы важные сообщения никогда не терялись бесшумно.
    """
    try:
        llm_response = await provider.chat_with_retry(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"## Original task\n{task_context}\n\n"
                        f"## Agent response\n{response}"
                    ),
                },
            ],
            tools=_EVALUATE_TOOL,
            model=model,
            max_tokens=256,
            temperature=0.0,
        )

        if not llm_response.has_tool_calls:
            logger.warning(
                "evaluate_response: вызов инструмента не возвращён, используем значение по умолчанию (уведомить)"
            )
            return True

        args = llm_response.tool_calls[0].arguments
        should_notify = args.get("should_notify", True)
        reason = args.get("reason", "")
        logger.info(
            "evaluate_response: следует_уведомить={}, причина={}", should_notify, reason
        )
        return bool(should_notify)

    except Exception:
        logger.exception(
            "evaluate_response: сбой, используем значение по умолчанию (уведомить)"
        )
        return True
