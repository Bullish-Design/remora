from __future__ import annotations

from pathlib import Path
from remora.core.events import _FrozenEvent
from remora.companion.events import CompanionSearchCompleted, CompanionConnectionsFound, CompanionConnection
from remora.companion.handlers.base import CompanionHandlerBase
from remora.companion.state import CompanionState

class ConnectionFinderHandler(CompanionHandlerBase):
    """Analyzes search results and context to find meaningful connections."""
    
    def __init__(self, agent_id: str, max_connections: int = 5, test_patterns: list[str] = None, doc_patterns: list[str] = None) -> None:
        super().__init__(agent_id)
        self.max_connections = max_connections
        self.test_patterns = test_patterns or ["test_", "_test.py", "tests/", "spec_", "_spec."]
        self.doc_patterns = doc_patterns or [".md", "docs/", "README", "NOTES", ".rst"]

    async def handle(self, event: _FrozenEvent, state: CompanionState) -> list[_FrozenEvent]:
        if not isinstance(event, CompanionSearchCompleted):
            return []
            
        context = state.context
        if not context:
            return []
            
        connections: list[CompanionConnection] = []
        current_file = context.file
        current_stem = Path(current_file).stem
        is_test = any(p in current_file for p in self.test_patterns)
        is_doc = any(p in current_file for p in self.doc_patterns)
        
        for result in event.results:
            res_file = result.file
            res_stem = Path(res_file).stem
            res_is_test = any(p in res_file for p in self.test_patterns)
            res_is_doc = any(p in res_file for p in self.doc_patterns)
            
            # Test connections
            if is_test != res_is_test and (current_stem in res_stem or res_stem in current_stem):
                connections.append(CompanionConnection(
                    source=current_file,
                    target=res_file,
                    relationship="tests" if is_test else "tested_by",
                    confidence=0.9
                ))
            
            # Doc connections
            if is_doc != res_is_doc and result.score > 0.5:
                connections.append(CompanionConnection(
                    source=current_file,
                    target=res_file,
                    relationship="documents" if is_doc else "documented_by",
                    confidence=result.score
                ))
                
            # Parallel implementations
            if context.content_type == "code" and result.content_type == "code" and context.structure_type in ("function", "class") and result.score > 0.7 and res_file != current_file:
                if context.structure_name.lower() in result.chunk_text.lower():
                    connections.append(CompanionConnection(
                        source=current_file,
                        target=res_file,
                        relationship="similar_pattern",
                        confidence=result.score
                    ))
            
        unique_conns = []
        seen = set()
        for conn in connections:
            key = (conn.source, conn.target, conn.relationship)
            if key not in seen:
                seen.add(key)
                unique_conns.append(conn)
                
        return [CompanionConnectionsFound(connections=tuple(unique_conns[:self.max_connections]))]
