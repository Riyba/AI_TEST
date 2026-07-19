"""Thin provider-agnostic LLM layer. Anthropic is the default provider.

The interface is a single `complete()` call taking optional tool definitions
and returning raw content blocks plus usage, so a different provider can be
swapped in by implementing LLMProvider without touching graph code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from anthropic import AsyncAnthropic

from .config import get_settings

# Models offered in the UI. Per-node model choice lets you use Sonnet for
# reasoning steps and Haiku for cheap/fast steps.
AVAILABLE_MODELS = [
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]

# Opus 4.8 and Sonnet 5 reject non-default sampling params (400); only pass
# temperature on models that still accept it.
SAMPLING_PARAM_MODELS = {"claude-sonnet-4-6", "claude-haiku-4-5"}


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    stop_reason: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_content: list[Any] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(Protocol):
    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...


class AnthropicProvider:
    def __init__(self) -> None:
        settings = get_settings()
        # Falls back to the SDK's normal env/credential resolution if unset.
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key or None,
            base_url=settings.anthropic_base_url,
        )
        self._max_tokens = settings.llm_max_tokens

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or self._max_tokens,
            "system": system or "You are a helpful software engineering agent.",
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if temperature is not None and model in SAMPLING_PARAM_MODELS:
            kwargs["temperature"] = temperature

        response = await self._client.messages.create(**kwargs)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, input=dict(block.input))
                )
        return LLMResponse(
            text="\n".join(text_parts),
            stop_reason=response.stop_reason,
            tool_calls=tool_calls,
            raw_content=response.content,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = AnthropicProvider()
    return _provider
