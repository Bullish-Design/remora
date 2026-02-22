# examples/treesitter_swarm/models/node.py
from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field

class NodeEmbeddingSpace(BaseModel):
    model_config = ConfigDict(frozen=True)
    
    syntax_vector: List[float] = Field(default_factory=list, description="Vector representing literal source code text")
    semantic_vector: List[float] = Field(default_factory=list, description="Vector representing docstrings and summaries")
    type_vector: List[float] = Field(default_factory=list, description="Vector representing structural inputs/outputs")
    topology_vector: List[float] = Field(default_factory=list, description="Vector representing AST relationship graph")

class TreeSitterNode(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    node_id: str
    node_type: str = Field(description="e.g., class_definition, function_definition")
    code_snippet: str
    start_byte: int
    end_byte: int
    
    # Graph relationships
    parent_id: Optional[str] = None
    child_ids: List[str] = Field(default_factory=list)
    sibling_ids: List[str] = Field(default_factory=list)
    
    # Embeddings
    embeddings: Optional[NodeEmbeddingSpace] = None
    
    def get_context_window(self) -> str:
        """Returns the specific snippet this node represents."""
        return self.code_snippet

    def is_leaf(self) -> bool:
        """Determines if this node has no children."""
        return len(self.child_ids) == 0
