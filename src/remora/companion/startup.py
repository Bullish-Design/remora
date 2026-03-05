from __future__ import annotations

import asyncio
from remora.companion.config import CompanionConfig
from remora.companion.state import CompanionState
from remora.companion.indexing_service import IndexingService
from remora.companion.dispatcher import CompanionDispatcher, HandlerConfig
from remora.companion.events import CompanionSessionTick

# Handlers
from remora.companion.handlers.context_extractor import ContextExtractorHandler
from remora.companion.handlers.edit_summarizer import EditSummarizerHandler
from remora.companion.handlers.search_handler import SearchHandler
from remora.companion.handlers.indexing_handler import IndexingHandler
from remora.companion.handlers.connection_finder import ConnectionFinderHandler
from remora.companion.handlers.task_inferrer import TaskInferrerHandler
from remora.companion.handlers.claim_checker import ClaimCheckerHandler
from remora.companion.handlers.sidebar_composer import SidebarComposerHandler

HANDLER_CONFIGS = {
    "companion.sidebar_composer": HandlerConfig(
        handler_id="companion.sidebar_composer",
        debounce_ms=150,
    ),
    "companion.edit_summarizer": HandlerConfig(
        handler_id="companion.edit_summarizer",
        debounce_ms=500,
    ),
}

async def start_companion(
    event_store,
    event_bus,
    cairn_service,
    config: CompanionConfig | None = None,
) -> CompanionDispatcher:
    cfg = config or CompanionConfig()
    
    # 1. Create CompanionState projection
    state = CompanionState()
    
    # 2. Create IndexingService
    indexing = IndexingService(cfg.indexing)
    await indexing.initialize()
    
    # 3. Create handlers
    handlers = {
        "companion.context_extractor": ContextExtractorHandler("companion.context_extractor"),
        "companion.edit_summarizer": EditSummarizerHandler("companion.edit_summarizer"),
        "companion.search_handler": SearchHandler("companion.search_handler", indexing),
        "companion.indexing_handler": IndexingHandler("companion.indexing_handler", indexing),
        "companion.connection_finder": ConnectionFinderHandler("companion.connection_finder"),
        "companion.task_inferrer": TaskInferrerHandler("companion.task_inferrer"),
        "companion.claim_checker": ClaimCheckerHandler("companion.claim_checker"),
        "companion.sidebar_composer": SidebarComposerHandler("companion.sidebar_composer"),
    }
    
    # 4. Initialize Cairn workspaces
    for handler in handlers.values():
        if hasattr(handler, "initialize"):
            await handler.initialize(cairn_service)
            
    # 5. Optionally index workspace
    if cfg.auto_index:
        await indexing.index_directory(cfg.workspace_path)
        
    # 6. Create dispatcher
    dispatcher = CompanionDispatcher(
        event_store=event_store,
        event_bus=event_bus,
        state=state,
        handlers=handlers,
        handler_configs=HANDLER_CONFIGS,
        session_id=cfg.session_id,
    )
    await dispatcher.start()
    
    # 7. Start the session tick
    async def tick_loop():
        tick = 0
        while True:
            await asyncio.sleep(30)
            tick += 1
            event = CompanionSessionTick(
                elapsed_ms=tick * 30000, tick_number=tick
            )
            await event_store.append(cfg.session_id, event)
            await event_bus.publish(event)
            
    asyncio.create_task(tick_loop())
    
    return dispatcher
