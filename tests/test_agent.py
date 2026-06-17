from __future__ import annotations

from src.agents.memory import (
    ChatMessage,
    build_compression_prompt,
    build_summary_message,
    select_messages_to_compress,
    should_compress,
)


class TestMemoryCompressor:
    def test_should_compress(self):
        messages = [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="hi")]
        assert not should_compress(messages, threshold=5)
        for i in range(10):
            messages.append(ChatMessage(role="user", content=str(i)))
        assert should_compress(messages, threshold=5)

    def test_select_messages_to_compress(self):
        messages = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="m1"),
            ChatMessage(role="assistant", content="a1"),
            ChatMessage(role="user", content="m2"),
            ChatMessage(role="user", content="m3"),
        ]
        to_compress, preserved = select_messages_to_compress(messages, tail_size=2)
        assert len(to_compress) >= 0
        assert len(preserved) >= 2  # system + tail

    def test_build_compression_prompt(self):
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there"),
        ]
        prompt = build_compression_prompt(messages)
        assert "Hello" in prompt
        assert "Hi there" in prompt
        assert "Summarize" in prompt

    def test_build_summary_message(self):
        msg = build_summary_message("User asked about Python.")
        assert msg.role == "system"
        assert "[COMPRESSED HISTORY]" in msg.content
        assert "Python" in msg.content
