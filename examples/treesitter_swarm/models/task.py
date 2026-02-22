# examples/treesitter_swarm/models/task.py
from __future__ import annotations
from typing import Optional, List, Any
from pydantic import BaseModel, Field

class TaskResult(BaseModel):
    success: bool
    final_snippet: Optional[str] = None
    tests_passed: bool = Field(default=False)
    error_message: Optional[str] = None

class SwarmTask(BaseModel):
    task_id: str
    target_node_id: str
    intent_description: str
    desired_final_state: str
    
    # Hierarchical delegation tracking
    subtasks: List[SwarmTask] = Field(default_factory=list)
    parent_task_id: Optional[str] = None
    
    status: str = Field(default="pending", description="pending, in_progress, completed, failed")
    result: Optional[TaskResult] = None

    def add_subtask(self, subtask: SwarmTask) -> None:
        """Adds a child node execution task to this branch."""
        self.subtasks.append(subtask)

    def determine_status(self) -> str:
        """Recursive check on subtask completion."""
        if not self.subtasks:
            return self.status
            
        if any(t.status == "failed" for t in self.subtasks):
            return "failed"
        if all(t.status == "completed" for t in self.subtasks):
            return "completed"
        return "in_progress"
