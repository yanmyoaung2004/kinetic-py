from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("kinetic.compression")

_HEADROOM_AVAILABLE: bool | None = None


def _check_headroom() -> bool:
    global _HEADROOM_AVAILABLE
    if _HEADROOM_AVAILABLE is not None:
        return _HEADROOM_AVAILABLE
    try:
        import headroom  # noqa: F401
        _HEADROOM_AVAILABLE = True
    except ImportError:
        _HEADROOM_AVAILABLE = False
        logger.warning("headroom-ai not installed. Install with: pip install headroom-ai")
    return _HEADROOM_AVAILABLE


def is_enabled() -> bool:
    return os.environ.get("HEADROOM_COMPRESSION", "0") == "1" and _check_headroom()


async def compress_messages(
    messages: list[Any],
    model: str | None = None,
) -> list[Any]:
    if not is_enabled():
        return messages
    if not messages:
        return messages

    from src.types.llm import ChatMessage

    has_chatmessage = any(isinstance(m, ChatMessage) for m in messages)

    try:
        from headroom import CompressConfig, compress

        target_ratio_str = os.environ.get("HEADROOM_COMPRESSION_RATIO", "")
        target_ratio = float(target_ratio_str) if target_ratio_str else None

        config = CompressConfig(
            compress_user_messages=False,
            compress_system_messages=True,
            protect_recent=4,
            target_ratio=target_ratio,
            min_tokens_to_compress=250,
        )

        if has_chatmessage:
            dict_messages = [m.to_dict() for m in messages]
        else:
            dict_messages = messages

        resolved_model = model or os.environ.get("HEADROOM_MODEL", "gpt-4o")
        result = compress(dict_messages, model=resolved_model, config=config)

        if result.tokens_saved > 0:
            logger.info(
                "Compressed %d -> %d tokens (%.0f%% saved, %s)",
                result.tokens_before,
                result.tokens_after,
                result.compression_ratio * 100,
                ", ".join(result.transforms_applied) or "none",
            )

        if has_chatmessage:
            return [ChatMessage.from_dict(m) for m in result.messages]
        return result.messages

    except Exception as exc:
        logger.warning("Compression failed, using original messages: %s", exc)
        return messages
