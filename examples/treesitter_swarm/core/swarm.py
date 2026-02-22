# examples/treesitter_swarm/core/swarm.py
from __future__ import annotations
from typing import Optional, List, Dict
from pydantic import BaseModel, ConfigDict, Field

from examples.treesitter_swarm.models.node import TreeSitterNode, NodeEmbeddingSpace
from examples.treesitter_swarm.models.agent import NodeAgent
from examples.treesitter_swarm.models.task import SwarmTask

class SupervisorLoRA(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    # Intent decoding configuration
    model_name: str = Field(default="supervisor-planner-lora-v2")
    
    def decode_intent_to_task(self, user_prompt: str, target_node: TreeSitterNode) -> SwarmTask:
        """
        Decodes a natural language user prompt into a defined Final State 
        task that can be handed directly to a Swarm entrypoint node.
        """
        # Note: In reality, this queries vector search spaces to understand dependencies
        return SwarmTask(
            task_id="task-master-1",
            target_node_id=target_node.node_id,
            intent_description=user_prompt,
            desired_final_state="Refactored node and all subnodes conform to user request."
        )

class AgentSwarm(BaseModel):
    """
    The orchestrator handling the creation, delegation, and state synchronization
    of node-specific agents.
    """
    swarm_id: str
    supervisor: SupervisorLoRA = Field(default_factory=SupervisorLoRA)
    
    # Active agents by node_id
    _active_agents: Dict[str, NodeAgent] = PrivateAttr(default_factory=dict)
    
    def initialize_agent_for_node(self, node: TreeSitterNode) -> NodeAgent:
        """
        Factory method to spin up the correct 'tiny' expert model dependent
        on the node topological type.
        """
        # E.g. finding 'tiny-expression-expert-v1'
        reasoning_model = f"tiny-{node.node_type}-expert-v1"
        
        agent = NodeAgent(
            agent_id=f"agent-{node.node_id}",
            node=node,
            reasoning_model_id=reasoning_model,
            sandbox_session_id=f"sandbox-{self.swarm_id}-{node.node_id}"
        )
        self._active_agents[node.node_id] = agent
        return agent

    def execute_swarm(self, user_request: str, root_node: TreeSitterNode) -> bool:
        """
        Entrypoint for the swarm graph traversal execution.
        """
        # 1. Supervisor translates prompt into a structured SwarmTask
        task = self.supervisor.decode_intent_to_task(user_request, root_node)
        
        # 2. Spin up the top-level Agent
        entry_agent = self.initialize_agent_for_node(root_node)
        
        # 3. Begin Fan-Out execution (Agent may recursively call Swarm to spin up children)
        # Assuming true Smalltalk OOP, objects send messages to each other directly.
        result = entry_agent.execute(task)
        
        return result.success

