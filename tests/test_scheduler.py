from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from src.agents.tasks.scheduler import (
    add_task,
    get_overdue_tasks,
    list_tasks,
    mark_task_run,
    remove_task,
)


class TestScheduler:
    def test_add_and_list_task(self, tmp_path):
        original_cwd = Path.cwd()
        import os

        os.chdir(tmp_path)
        try:
            task = add_task(
                "test-agent",
                {
                    "description": "Test task",
                    "type": "once",
                    "next_run": (datetime.now() + timedelta(hours=1)).isoformat(),
                    "dispatch_to": "test-agent",
                    "query": "run test",
                },
            )
            assert task.id.startswith("task_")
            assert task.description == "Test task"

            tasks = list_tasks("test-agent")
            assert len(tasks) == 1
            assert tasks[0].id == task.id
        finally:
            os.chdir(original_cwd)

    def test_remove_task(self, tmp_path):
        import os

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            task = add_task(
                "test-agent",
                {
                    "description": "To remove",
                    "type": "once",
                    "next_run": (datetime.now() + timedelta(hours=1)).isoformat(),
                    "dispatch_to": "test-agent",
                    "query": "remove me",
                },
            )
            assert remove_task("test-agent", task.id)
            assert not remove_task("test-agent", "nonexistent")
            assert len(list_tasks("test-agent")) == 0
        finally:
            os.chdir(original_cwd)

    def test_get_overdue_tasks(self, tmp_path):
        import os

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            add_task(
                "test-agent",
                {
                    "description": "Past task",
                    "type": "once",
                    "next_run": (datetime.now() - timedelta(minutes=5)).isoformat(),
                    "dispatch_to": "test-agent",
                    "query": "past",
                },
            )
            add_task(
                "test-agent",
                {
                    "description": "Future task",
                    "type": "once",
                    "next_run": (datetime.now() + timedelta(hours=5)).isoformat(),
                    "dispatch_to": "test-agent",
                    "query": "future",
                },
            )
            overdue = get_overdue_tasks()
            overdue_descriptions = [item["task"]["description"] for item in overdue]
            assert "Past task" in overdue_descriptions
            assert "Future task" not in overdue_descriptions
        finally:
            os.chdir(original_cwd)

    def test_mark_task_run_once(self, tmp_path):
        import os

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            task = add_task(
                "test-agent",
                {
                    "description": "One time",
                    "type": "once",
                    "next_run": (datetime.now() - timedelta(minutes=1)).isoformat(),
                    "dispatch_to": "test-agent",
                    "query": "once",
                },
            )
            mark_task_run("test-agent", task.id)
            assert len(list_tasks("test-agent")) == 0  # Should be removed
        finally:
            os.chdir(original_cwd)

    def test_mark_task_run_interval(self, tmp_path):
        import os

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            task = add_task(
                "test-agent",
                {
                    "description": "Recurring",
                    "type": "interval",
                    "interval_ms": 60000,
                    "next_run": (datetime.now() - timedelta(minutes=1)).isoformat(),
                    "dispatch_to": "test-agent",
                    "query": "interval",
                },
            )
            mark_task_run("test-agent", task.id)
            tasks = list_tasks("test-agent")
            assert len(tasks) == 1  # Should still exist
            assert tasks[0].last_run is not None
            # next_run should be advanced
            next_time = datetime.fromisoformat(tasks[0].next_run)
            assert next_time > datetime.now() - timedelta(seconds=10)
        finally:
            os.chdir(original_cwd)

    def test_get_overdue_tasks_empty(self, tmp_path):
        import os

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            assert get_overdue_tasks() == []
        finally:
            os.chdir(original_cwd)
