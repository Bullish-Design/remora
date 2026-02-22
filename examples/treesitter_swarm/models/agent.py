# examples/treesitter_swarm/models/agent.py
from __future__ import annotations
from typing import Optional, List, Dict, Any, Callable
from pydantic import BaseModel, Field, PrivateAttr

from examples.treesitter_swarm.models.node import TreeSitterNode
from examples.treesitter_swarm.models.task import SwarmTask, TaskResult

class NodeAgent(BaseModel):
    """
    Encapsulates the dual-model persona required for a specific AST node level.
    """
    agent_id: str
    node: TreeSitterNode
    
    # We define what specific reasoning model powers this agent.
    # Note: 'tiny-function-expert-v1' or 'tiny-class-expert-v1'
    reasoning_model_id: str 
    
    # We always pair with a FunctionGemma model
    tool_model_id: str = Field(default="function-gemma-270m")
    
    # Internal sandboxing
    sandbox_session_id: str
    
    _tools: Dict[str, Callable[..., Any]] = PrivateAttr(default_factory=dict)

    def register_tool(self, name: str, func: Callable[..., Any]) -> None:
        """Binds a Grail script or utility to this specific node agent."""
        self._tools[name] = func

    def execute(self, task: SwarmTask) -> TaskResult:
        """
        Executes the provided task recursively. It will try to accomplish the
        change on its immediate 'node' scope or delegate subtasks if the change
        affects specific child nodes it lacks structural expertise for.
        """
        if task.status != "pending":
            return TaskResult(success=False, error_message="Task is not pending.")
            
        # Mock execution logic
        task.status = "in_progress"
        
        # In a real scenario, this involves:
        # 1. Generating code changes via the fine-tuned Reasoning Model
        # 2. Writing Unit Tests to confirm 'desired_final_state' is met
        # 3. Running tests via the Tool Model in the Cairn sandbox
        
        return TaskResult(
            success=True, 
            final_snippet=f"# Modified {self.node.node_type} logic\n{self.node.code_snippet}",
            tests_passed=True
        )
