from __future__ import annotations

import os

from pathlib import Path

import pytest

from src.agents.tools.execute_command import create_execute_command_tool
from src.agents.tools.file_tools import (
    create_delete_file_tool,
    create_edit_file_tool,
    create_list_files_tool,
    create_read_file_tool,
    create_undo_file_tool,
    create_write_file_tool,
)
from src.agents.tools.registry import ToolHandler, ToolRegistry, create_send_message_tool, create_web_search_tool
from src.agents.tools.schedule_task import _parse_time_to_delay, create_get_time_tool
from src.agents.tools.system_tools import create_get_system_info_tool, create_read_env_var_tool
from src.types.agent import ToolDefinition


class TestToolRegistry:
    @pytest.mark.asyncio
    async def test_register_and_execute(self):
        registry = ToolRegistry()

        async def _fake_exec(args, ctx=None):
            return f"Executed {args}"

        registry.register(
            ToolHandler(
                definition=ToolDefinition(
                    function={
                        "name": "test_tool",
                        "description": "",
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    }
                ),
                execute=_fake_exec,
            )
        )
        assert registry.has("test_tool")
        result = await registry.execute("test_tool", {"key": "val"})
        assert "Executed" in result

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        registry = ToolRegistry()
        result = await registry.execute("unknown", {})
        assert "Unknown tool" in result

    def test_get_definitions(self):
        registry = ToolRegistry()
        registry.register(create_send_message_tool())
        defs = registry.get_definitions()
        assert len(defs) == 1
        assert defs[0].function["name"] == "send_message"


class TestSendMessageTool:
    @pytest.mark.asyncio
    async def test_send_message(self):
        async def mock_dispatch(target, msg, depth):
            return f"Response from {target}"

        tool = create_send_message_tool(mock_dispatch)
        result = await tool.execute({"target": "agent2", "message": "hello"}, None)
        assert "agent2" in result
        assert "Response from" in result


class TestWebSearchTool:
    @pytest.mark.asyncio
    async def test_no_api_key(self):
        if "BRAVE_API_KEY" in os.environ:
            del os.environ["BRAVE_API_KEY"]
        tool = create_web_search_tool()
        result = await tool.execute({"query": "test"}, None)
        assert "BRAVE_API_KEY is missing" in result


class TestExecuteCommandTool:
    @pytest.mark.asyncio
    async def test_whitelisted_command(self):
        tool = create_execute_command_tool()
        cmd = "hostname"
        result = await tool.execute({"command": cmd, "args": []}, None)
        assert "ERROR" not in result
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_blocked_command(self):
        tool = create_execute_command_tool()
        result = await tool.execute({"command": "rm", "args": []}, None)
        assert "not on the whitelist" in result


class TestFileTools:
    @pytest.fixture(autouse=True)
    def _setup_cwd(self, tmp_path):
        self._orig_cwd = Path.cwd()
        os.chdir(tmp_path)
        yield
        os.chdir(self._orig_cwd)

    @pytest.mark.asyncio
    async def test_write_and_read(self):
        write_tool = create_write_file_tool()
        read_tool = create_read_file_tool()

        write_result = await write_tool.execute({"path": "test.txt", "content": "hello world"}, None)
        assert "Wrote" in write_result
        result = await read_tool.execute({"path": "test.txt"}, None)
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_edit_file(self):
        write_tool = create_write_file_tool()
        edit_tool = create_edit_file_tool()
        read_tool = create_read_file_tool()

        r1 = await write_tool.execute({"path": "edit.txt", "content": "hello world foo"}, None)
        assert "Wrote" in r1, f"Write failed: {r1}"

        file_content = await read_tool.execute({"path": "edit.txt"}, None)
        assert file_content == "hello world foo", f"File content wrong: {file_content}"

        r2 = await edit_tool.execute({"path": "edit.txt", "old_text": "world", "new_text": "there"}, None)
        assert "Edited" in r2, f"Edit failed: {r2}"

        result = await read_tool.execute({"path": "edit.txt"}, None)
        assert result == "hello there foo", f"After edit: {result}"

    @pytest.mark.asyncio
    async def test_delete_and_undo(self):
        write_tool = create_write_file_tool()
        delete_tool = create_delete_file_tool()
        undo_tool = create_undo_file_tool()
        read_tool = create_read_file_tool()

        r1 = await write_tool.execute({"path": "del.txt", "content": "delete me"}, None)
        assert "Wrote" in r1, f"Write failed: {r1}"

        file_content = await read_tool.execute({"path": "del.txt"}, None)
        assert file_content == "delete me", f"File content wrong: {file_content}"

        r2 = await delete_tool.execute({"path": "del.txt"}, None)
        assert "Deleted" in r2, f"Delete failed: {r2}"

        result = await read_tool.execute({"path": "del.txt"}, None)
        assert "not found" in result.lower(), f"After delete: {result}"

        r3 = await undo_tool.execute({"path": "del.txt"}, None)
        assert "reverted" in r3, f"Undo failed: {r3}"

        result = await read_tool.execute({"path": "del.txt"}, None)
        assert result == "delete me", f"After undo: {result}"

    @pytest.mark.asyncio
    async def test_list_files(self):
        write_tool = create_write_file_tool()
        await write_tool.execute({"path": "list_test.txt", "content": "test"}, None)
        result = await create_list_files_tool().execute({"path": "."}, None)
        assert "list_test.txt" in result


class TestScheduleTask:
    def test_parse_time_to_delay_iso(self):
        from datetime import datetime, timedelta

        future = (datetime.now() + timedelta(hours=2)).isoformat()
        delay = _parse_time_to_delay(future)
        assert delay is not None
        assert delay > 0

    def test_parse_time_to_delay_12h(self):
        delay = _parse_time_to_delay("11:59 PM")
        assert delay is not None

    def test_parse_time_to_delay_24h(self):
        delay = _parse_time_to_delay("23:59")
        assert delay is not None

    def test_parse_time_to_delay_invalid(self):
        assert _parse_time_to_delay("not a time") is None


class TestGetTimeTool:
    @pytest.mark.asyncio
    async def test_get_time(self):
        tool = create_get_time_tool()
        result = await tool.execute({}, None)
        assert "Current time" in result


class TestGetSystemInfoTool:
    @pytest.mark.asyncio
    async def test_system_info(self):
        tool = create_get_system_info_tool()
        result = await tool.execute({}, None)
        assert "OS:" in result


class TestReadEnvVarTool:
    @pytest.mark.asyncio
    async def test_read_env(self):
        os.environ["KINETIC_TEST_VAR"] = "test_value"
        tool = create_read_env_var_tool()
        result = await tool.execute({"name": "KINETIC_TEST_VAR"}, None)
        assert "test_value" in result
        os.environ.pop("KINETIC_TEST_VAR", None)

    @pytest.mark.asyncio
    async def test_sensitive_masked(self):
        os.environ["KINETIC_API_KEY"] = "sk-secret123"
        tool = create_read_env_var_tool()
        result = await tool.execute({"name": "KINETIC_API_KEY"}, None)
        assert "hidden" in result
        assert "sk-" not in result
        os.environ.pop("KINETIC_API_KEY", None)

    @pytest.mark.asyncio
    async def test_not_set(self):
        tool = create_read_env_var_tool()
        result = await tool.execute({"name": "KINETIC_NONEXISTENT_VAR"}, None)
        assert "not set" in result
