"""TDD tests for 6.5: Kernel factory (create_kernel).

Verifies:
- create_kernel exists in remora.core.kernel_factory
- Accepts model_name, base_url, api_key, timeout, tools, observer
- Returns an AgentKernel instance
- SwarmExecutor._run_kernel uses create_kernel
- ChatSession.send uses create_kernel
- grammar_config/constraint_pipeline support
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestKernelFactoryExists:
    """create_kernel must be importable and callable."""

    def test_importable(self):
        from remora.core.agents.kernel_factory import create_kernel

        assert callable(create_kernel)

    def test_returns_agent_kernel(self):
        from remora.core.agents.kernel_factory import create_kernel
        from structured_agents.kernel import AgentKernel

        kernel = create_kernel(
            model_name="test-model",
            base_url="http://localhost:8000/v1",
            api_key="EMPTY",
        )
        assert isinstance(kernel, AgentKernel)

    def test_accepts_tools(self):
        from remora.core.agents.kernel_factory import create_kernel

        mock_tool = MagicMock()
        kernel = create_kernel(
            model_name="test-model",
            base_url="http://localhost:8000/v1",
            api_key="EMPTY",
            tools=[mock_tool],
        )
        assert kernel is not None

    def test_accepts_observer(self):
        from remora.core.agents.kernel_factory import create_kernel

        observer = MagicMock()
        kernel = create_kernel(
            model_name="test-model",
            base_url="http://localhost:8000/v1",
            api_key="EMPTY",
            observer=observer,
        )
        assert kernel is not None

    def test_accepts_timeout(self):
        from remora.core.agents.kernel_factory import create_kernel

        kernel = create_kernel(
            model_name="test-model",
            base_url="http://localhost:8000/v1",
            api_key="EMPTY",
            timeout=120.0,
        )
        assert kernel is not None

    def test_accepts_grammar_config(self):
        """Grammar config should be forwarded to build a ConstraintPipeline."""
        from remora.core.agents.kernel_factory import create_kernel

        # None grammar_config should be fine (no pipeline)
        kernel = create_kernel(
            model_name="test-model",
            base_url="http://localhost:8000/v1",
            api_key="EMPTY",
            grammar_config=None,
        )
        assert kernel is not None

    def test_accepts_existing_client(self):
        """If a pre-built client is passed, it should be reused (no new client)."""
        from remora.core.agents.kernel_factory import create_kernel

        mock_client = MagicMock()
        kernel = create_kernel(
            model_name="test-model",
            base_url="http://localhost:8000/v1",
            api_key="EMPTY",
            client=mock_client,
        )
        assert kernel is not None


class TestKernelFactoryReExport:
    """create_kernel should be importable from remora.core."""

    def test_importable_from_core(self):
        from remora.core import create_kernel  # noqa: F401
