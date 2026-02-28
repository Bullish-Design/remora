import asyncio
from pathlib import Path
from remora.core.config import load_config
from remora.core.events import ManualTriggerEvent
from remora.core.event_store import EventStore
from remora.core.event_bus import EventBus
from remora.core.swarm_state import SwarmState, AgentMetadata


async def inject_event():
    config = load_config()
    db_path = Path(config.swarm_root) / config.swarm_id / "workspace.db"

    # 1. Connect to same DB
    event_bus = EventBus()
    event_store = EventStore(db_path, event_bus=event_bus)
    await event_store.initialize()

    swarm_state = SwarmState(db_path)
    await swarm_state.initialize()

    # 2. Add a mock agent so Neovim actually finds it when you hover
    await swarm_state.upsert(
        AgentMetadata(
            agent_id="function_definition_utils_15",
            node_type="function_definition",
            name="format_date",
            full_name="src.utils.format_date",
            file_path="src/utils.py",
            start_line=15,
            end_line=25,
            status="ACTIVE",
        )
    )

    # 3. Fire a manual trigger at the new agent
    event = ManualTriggerEvent(
        to_agent="function_definition_utils_15",
        reason="Testing End to End integration",
    )

    # Writing to the EventStore will broadcast to the EventBus
    await event_store.append("demo_graph", event)

    print("Test event injected. Check localhost dashboard!")


if __name__ == "__main__":
    asyncio.run(inject_event())
