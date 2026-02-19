import sys
from pathlib import Path
import os

# Add project root and potential cairn location to path
sys.path.append(str(Path.cwd()))
cairn_path = Path.cwd() / ".context" / "cairn" / "src"
if cairn_path.exists():
    sys.path.append(str(cairn_path))
    print(f"Added {cairn_path} to sys.path")
else:
    print(f"Cairn path {cairn_path} not found")

try:
    from remora.config import load_config, OperationConfig
    from remora.orchestrator import Coordinator
    from remora.runner import FunctionGemmaRunner
    print("Imports successful")
except ImportError as e:
    print(f"Import failed: {e}")
    # Don't exit, try to debug
    # sys.exit(1)

try:
    config = load_config()
    print(f"Max queue size: {config.cairn.max_queue_size}")
    print(f"Retry config: {config.server.retry}")
    print(f"Test operation priority: {config.operations['test'].priority}")
except Exception as e:
    print(f"Config load failed: {e}")

# checking if TaskQueue can be instantiated (requires cairn)
try:
    from cairn.orchestrator.queue import TaskQueue
    tq = TaskQueue(max_size=10)
    print("TaskQueue instantiated successfully")
except ImportError:
    print("Cairn not found (ImportError), skipping TaskQueue instantiation check")
except Exception as e:
    print(f"TaskQueue instantiation failed: {e}")

# Check RetryStrategy
try:
    from cairn.utils.retry import RetryStrategy
    rs = RetryStrategy()
    print("RetryStrategy instantiated successfully")
except ImportError:
    print("Cairn not found (ImportError), skipping RetryStrategy instantiation check")
except Exception as e:
    print(f"RetryStrategy instantiation failed: {e}")
