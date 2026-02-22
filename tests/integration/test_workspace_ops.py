import pytest
import asyncio
from pathlib import Path
from remora.config import load_config
from remora.analyzer import RemoraAnalyzer
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_real_workspace_lifecycle(tmp_path: Path):
    """Test full cycle of creating a workspace, mocking a result, and merging it over Cairn overlay to disk."""
    
    # 1. Setup real project dir
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "target.py").write_text("def hello(): pass", encoding="utf-8")
    
    # 2. Setup Config
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    
    config_content = f"""
agents_dir: "{agents_dir.resolve().as_posix()}"
server:
  default_adapter: "demo"
operations:
  lint:
    enabled: true
    subagent: "lint.yaml"
"""
    config_file = tmp_path / "remora.yaml"
    config_file.write_text(config_content, encoding="utf-8")
    
    lint_agent = agents_dir / "lint.yaml"
    lint_agent_content = """
name: lint
version: "1.0"
model:
  plugin: function_gemma
initial_context:
  system_prompt: ""
  user_template: ""
max_turns: 5
termination_tool: submit_result
tools: []
registries: []
"""
    lint_agent.write_text(lint_agent_content, encoding="utf-8")
    
    config_dict = {"config": config_file}
    config = load_config(config_file)
    config.cairn.home = tmp_path / "cairn_home"
    
    analyzer = RemoraAnalyzer(config)
    
    def mock_runner_init(*args, **kwargs):
        class FakeRunner:
            def __init__(self, ctx, **_):
                self.ctx = ctx
            async def run(self):
                from remora.results import AgentResult, AgentStatus
                workspace_db = analyzer._workspace_db_path(self.ctx.agent_id)
                workspace_db.parent.mkdir(parents=True, exist_ok=True)
                workspace_db.write_text("dummy", encoding="utf-8")
                return AgentResult(status=AgentStatus.SUCCESS, workspace_id=self.ctx.agent_id, summary="Done", changed_files=[])
        return FakeRunner(kwargs.get('ctx'))
        
    with patch("remora.orchestrator.KernelRunner", side_effect=mock_runner_init):
        # Prevent actual cairn merge logic from trying to open a fake sqlite DB
        with patch.object(analyzer, '_cairn_merge', new_callable=MagicMock) as mock_merge:
            # 3. Analyze 
            results = await analyzer.analyze(paths=[project_dir], operations=["lint"])
            assert results.total_nodes > 0
            
            # Verify the workspace database was mapped correctly
            workspace_info = list(analyzer._workspaces.values())[0]
            workspace_id = workspace_info.workspace_id
            node_id = workspace_info.node_id
            workspace_db = analyzer._workspace_db_path(workspace_id)
            assert workspace_db.exists()
            
            # 4. Accept
            await analyzer.accept(node_id, "lint")
            
            # Mock merge should have been called
            mock_merge.assert_called_once_with(workspace_id)
