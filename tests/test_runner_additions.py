
def test_tool_choice_is_always_configured_value_even_on_last_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup response (doesn't matter much for this test, but need something)
    _patch_openai(monkeypatch, responses=[_tool_call_message("submit_result", {})])
    
    definition = _make_definition(max_turns=2)
    node = _make_node()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="ws-1",
        cairn_client=FakeCairnClient(),
        server_config=_make_server_config(),
        runner_config=RunnerConfig(tool_choice="auto"),
    )
    
    # Check turn 1
    assert runner._tool_choice_for_turn(1) == "auto"
    # Check turn 100 (way past max_turns)
    assert runner._tool_choice_for_turn(100) == "auto"


def test_runner_retries_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # We need a FakeAsyncOpenAI that fails once then succeeds
    class FlakyAsyncOpenAI(FakeAsyncOpenAI):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.fail_count = 0
            
        # We need to monkeypatch the chat.completions.create method specifically
        # But our FakeAsyncOpenAI structure is a bit complex to hook into easily without changing the class
        # So we'll rely on the _patch_openai helper to allow passing a custom factory or just modify the fake.
        pass

    # Better approach: modify FakeChatCompletions to fail N times
    class FlakyChatCompletions(FakeChatCompletions):
        def __init__(self, responses, fail_times=1, error=APIConnectionError(message="fail", request=None)):
            super().__init__(responses)
            self.fail_times = fail_times
            self.failures = 0
            self.error_to_raise = error

        async def create(self, **kwargs):
            if self.failures < self.fail_times:
                self.failures += 1
                raise self.error_to_raise
            return await super().create(**kwargs)

    # Custom factory for this test
    def _flaky_factory(*_, **kwargs):
        client = FakeAsyncOpenAI(
            base_url=kwargs["base_url"],
            api_key=kwargs["api_key"],
            timeout=kwargs["timeout"],
            responses=[_tool_call_message("submit_result", {})],
        )
        client.chat.completions = FlakyChatCompletions(
            responses=[_tool_call_message("submit_result", {})],
            fail_times=2, # Fail twice, succeed third time
            error=APIConnectionError(message="connection refused", request=None)
        )
        return client

    monkeypatch.setattr("remora.runner.AsyncOpenAI", _flaky_factory)

    definition = _make_definition()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=_make_node(),
        workspace_id="ws-1",
        cairn_client=FakeCairnClient(),
        server_config=_make_server_config(),
        runner_config=_make_runner_config(),
    )

    # fast forward retry usage of asyncio.sleep so test is fast
    async def _fake_sleep(_): pass
    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    result = asyncio.run(runner.run())
    assert result.status == "success"
