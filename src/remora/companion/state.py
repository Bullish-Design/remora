from __future__ import annotations

from remora.core.events import _FrozenEvent, CursorFocusEvent, ContentChangedEvent, FileSavedEvent

class CompanionState:
    """Read-only projection of companion event stream.
    
    Continuously updated as events arrive. Handlers read from this
    for current state instead of querying EventStore directly.
    """
    
    def __init__(self) -> None:
        self._latest: dict[str, _FrozenEvent] = {}
    
    def apply(self, event: _FrozenEvent) -> None:
        event_type = type(event).__name__
        if event_type.startswith("Companion") or event_type in (
            "CursorFocusEvent", "ContentChangedEvent", "FileSavedEvent"
        ):
            self._latest[event_type] = event
    
    @property
    def context(self) -> _FrozenEvent | None: # type hint later updated when imported
        return self._latest.get("CompanionContextExtracted")
    
    @property
    def search_results(self) -> _FrozenEvent | None:
        return self._latest.get("CompanionSearchCompleted")
    
    @property
    def connections(self) -> _FrozenEvent | None:
        return self._latest.get("CompanionConnectionsFound")
    
    @property
    def task(self) -> _FrozenEvent | None:
        return self._latest.get("CompanionTaskInferred")
    
    @property
    def claims(self) -> _FrozenEvent | None:
        return self._latest.get("CompanionClaimsChecked")
    
    @property
    def sidebar(self) -> _FrozenEvent | None:
        return self._latest.get("CompanionSidebarComposed")
    
    @property
    def edit_summary(self) -> _FrozenEvent | None:
        return self._latest.get("CompanionEditSummary")
