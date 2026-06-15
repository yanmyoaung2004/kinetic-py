from __future__ import annotations

from src.agents.memory import AgentMemory, ChatMessage


class TestAgentMemory:
    def test_init_creates_dir(self, tmp_workspace):
        mem = AgentMemory("test-agent", str(tmp_workspace))
        assert (tmp_workspace / "test-agent").exists()
        assert mem.session_id == "default"

    def test_append_and_retrieve(self, tmp_workspace):
        mem = AgentMemory("test-agent", str(tmp_workspace))
        mem.append(ChatMessage(role="user", content="hello"))
        mem.append(ChatMessage(role="assistant", content="world"))
        msgs = mem.get_messages()
        assert len(msgs) == 2
        assert msgs[0].content == "hello"
        assert msgs[1].content == "world"

    def test_persistence_across_instances(self, tmp_workspace):
        mem1 = AgentMemory("test-agent", str(tmp_workspace))
        mem1.append(ChatMessage(role="user", content="persist me"))
        del mem1

        mem2 = AgentMemory("test-agent", str(tmp_workspace))
        msgs = mem2.get_messages()
        assert len(msgs) == 1
        assert msgs[0].content == "persist me"

    def test_trim_respects_max(self, tmp_workspace):
        mem = AgentMemory("test-agent", str(tmp_workspace), max_messages=5)
        for i in range(10):
            mem.append(ChatMessage(role="user", content=f"msg {i}"))
        assert len(mem.get_messages()) <= 5

    def test_user_message_count(self, tmp_workspace):
        mem = AgentMemory("test-agent", str(tmp_workspace))
        mem.append(ChatMessage(role="user", content="u1"))
        mem.append(ChatMessage(role="assistant", content="a1"))
        mem.append(ChatMessage(role="user", content="u2"))
        assert mem.get_user_message_count() == 2

    def test_needs_compression(self, tmp_workspace):
        mem = AgentMemory("test-agent", str(tmp_workspace))
        mem.append(ChatMessage(role="system", content="sys"))
        for i in range(10):
            mem.append(ChatMessage(role="user" if i % 2 == 0 else "assistant", content=str(i)))
        assert mem.needs_compression(threshold=5)
        assert not mem.needs_compression(threshold=20)

    def test_session_isolation(self, tmp_workspace):
        mem1 = AgentMemory("test-agent", str(tmp_workspace), session_id="session-a")
        mem1.append(ChatMessage(role="user", content="session a msg"))
        del mem1

        mem2 = AgentMemory("test-agent", str(tmp_workspace), session_id="session-b")
        assert len(mem2.get_messages()) == 0

    def test_profile_crud(self, tmp_workspace):
        from src.agents.memory import UserProfile

        mem = AgentMemory("test-agent", str(tmp_workspace))
        assert mem.read_profile() is None

        profile = UserProfile(known_facts=["likes Python"], preferences=["concise"], last_updated="now", extraction_count=1)
        mem.write_profile(profile)
        loaded = mem.read_profile()
        assert loaded is not None
        assert loaded.known_facts == ["likes Python"]
        assert loaded.preferences == ["concise"]

    def test_reset_clears_history(self, tmp_workspace):
        mem = AgentMemory("test-agent", str(tmp_workspace))
        mem.append(ChatMessage(role="user", content="hello"))
        mem.reset()
        assert len(mem.get_messages()) == 0
        assert mem.get_user_message_count() == 0

    def test_refresh_system_prompt(self, tmp_workspace):
        mem = AgentMemory("test-agent", str(tmp_workspace))
        mem.append(ChatMessage(role="system", content="old prompt"))
        assert mem.refresh_system_prompt("new prompt")
        assert mem.get_messages()[0].content == "new prompt"
        # Second call should return False (already updated)
        assert not mem.refresh_system_prompt("new prompt")

    def test_compression_candidates(self, tmp_workspace):
        mem = AgentMemory("test-agent", str(tmp_workspace))
        mem.append(ChatMessage(role="system", content="sys"))
        for i in range(10):
            mem.append(ChatMessage(role="user", content=str(i)))
        candidates = mem.get_compression_candidates(tail_size=3)
        assert len(candidates) > 0  # 10 non-system - 3 tail = 7 candidates

    def test_apply_compression(self, tmp_workspace):
        mem = AgentMemory("test-agent", str(tmp_workspace))
        mem.append(ChatMessage(role="system", content="sys"))
        for i in range(10):
            mem.append(ChatMessage(role="user", content=str(i)))
        summary = ChatMessage(role="system", content="[COMPRESSED HISTORY] Summary")
        mem.apply_compression(summary, tail_size=3)
        msgs = mem.get_messages()
        assert any("[COMPRESSED HISTORY]" in m.content for m in msgs)

    def test_list_sessions(self, tmp_workspace):
        AgentMemory("test-agent", str(tmp_workspace), session_id="session-a")
        AgentMemory("test-agent", str(tmp_workspace), session_id="session-b")
        sessions = AgentMemory.list_sessions("test-agent", str(tmp_workspace))
        assert sorted(sessions) == ["session-a", "session-b"]

    def test_destroy(self, tmp_workspace):
        mem = AgentMemory("test-agent", str(tmp_workspace))
        mem.append(ChatMessage(role="user", content="test"))
        mem.destroy()
        assert not (tmp_workspace / "test-agent").exists()
