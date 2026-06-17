from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.tasks.pipeline import (
    Pipeline,
    PipelineStep,
    delete_pipeline,
    execute_pipeline,
    get_pipeline,
    list_pipelines,
    save_pipeline,
)


class TestPipeline:
    def test_save_and_get(self, tmp_path):
        original_cwd = Path.cwd()
        import os

        os.chdir(tmp_path)
        try:
            pipeline = save_pipeline(
                {
                    "name": "Test Pipeline",
                    "description": "A test",
                    "steps": [
                        {"id": "step_0", "agent": "agent1", "prompt": "Do {{task}}", "output_var": "result"},
                    ],
                }
            )
            assert pipeline.id is not None
            assert pipeline.name == "Test Pipeline"

            loaded = get_pipeline(pipeline.id)
            assert loaded is not None
            assert loaded.name == "Test Pipeline"
            assert len(loaded.steps) == 1
        finally:
            os.chdir(original_cwd)

    def test_list_pipelines(self, tmp_path):
        import os

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            save_pipeline({"name": "Pipe 1", "steps": []})
            save_pipeline({"name": "Pipe 2", "steps": []})
            pipelines = list_pipelines()
            assert len(pipelines) == 2
        finally:
            os.chdir(original_cwd)

    def test_delete_pipeline(self, tmp_path):
        import os

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            p = save_pipeline({"name": "To Delete", "steps": []})
            assert delete_pipeline(p.id)
            assert not delete_pipeline("nonexistent")
            assert get_pipeline(p.id) is None
        finally:
            os.chdir(original_cwd)

    def test_save_preserves_created_on_update(self, tmp_path):
        import os

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            p1 = save_pipeline({"name": "Original", "steps": []})
            import time

            time.sleep(0.01)
            p2 = save_pipeline({"id": p1.id, "name": "Updated", "steps": []})
            assert p2.created == p1.created  # Created timestamp preserved
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_execute_pipeline(self, tmp_path):
        import os

        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            pipeline = Pipeline(
                id="test_exec",
                name="Exec Test",
                description="",
                steps=[
                    PipelineStep(id="s1", agent="agent1", prompt="Do the thing with {{input}}", output_var="step1_out"),
                ],
                created="now",
            )

            async def mock_dispatch(agent_id, message):
                return f"Result for: {message}"

            outputs = await execute_pipeline(pipeline, {"input": "my data"}, mock_dispatch)
            assert "step1_out" in outputs
            assert "Result for:" in outputs["step1_out"]
        finally:
            os.chdir(original_cwd)
