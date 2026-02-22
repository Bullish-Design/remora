import pytest
from pathlib import Path
from remora.config import RemoraConfig, OperationConfig

def test_config_precedence_cairn_home_default():
    \"\"\"Test that cairn.home defaults to agents_dir/.cairn when not provided.\"\"\"
    config = RemoraConfig(agents_dir=Path("/custom/agents"))
    
    # After validation, cairn.home should be populated based on agents_dir
    assert config.cairn.home == Path("/custom/agents/.cairn")

def test_config_precedence_cairn_home_override():
    \"\"\"Test that an explicit cairn.home is respected.\"\"\"
    config = RemoraConfig(
        agents_dir=Path("/custom/agents"),
        cairn={"home": Path("/explicit/home")}
    )
    
    # Explicit cairn.home should override the default logic
    assert config.cairn.home == Path("/explicit/home")

def test_config_precedence_model_id_default():
    \"\"\"Test that operations without a model_id inherit from server.default_adapter.\"\"\"
    config = RemoraConfig(
        server={"default_adapter": "custom-global-model"},
        operations={
            "test_op_no_model": OperationConfig(subagent="test_subagent_1"),
            "test_op_with_model": OperationConfig(subagent="test_subagent_2", model_id="specific-op-model")
        }
    )
    
    # Operation without model_id should inherit the global default
    assert config.operations["test_op_no_model"].model_id == "custom-global-model"
    
    # Operation with explicit model_id should keep its value
    assert config.operations["test_op_with_model"].model_id == "specific-op-model"
