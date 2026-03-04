"""Demo harness — drives the CompanionRuntime through scripted scenarios.

Orchestrates:
1. Indexing the example workspace
2. Playing scenario steps (cursor movements)
3. Waiting for agent cascade to complete
4. Rendering the result via TerminalRenderer
5. Optionally recording to asciicast and converting to GIF

Usage:
    python -m remora_demo.companion.demo
    python -m remora_demo.companion.demo --scenario coding
    python -m remora_demo.companion.demo --scenario research
    python -m remora_demo.companion.demo --list
    python -m remora_demo.companion.demo --plain output.txt
    python -m remora_demo.companion.demo --record demo.cast
    python -m remora_demo.companion.demo --record demo.cast --gif demo.gif
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from remora_demo.companion.demo.recording import AsciicastWriter
from remora_demo.companion.demo.renderer import (
    Ansi,
    RenderConfig,
    TerminalRenderer,
)
from remora_demo.companion.demo.scenarios import DemoScenario, DemoStep

if TYPE_CHECKING:
    from remora_demo.companion.runtime import CompanionRuntime

logger = logging.getLogger(__name__)


@dataclass
class DemoConfig:
    """Configuration for the demo harness."""

    # Rendering
    render: RenderConfig = field(default_factory=RenderConfig)

    # Timing
    agent_settle_time: float = 0.8  # Seconds to wait for agent cascade
    step_transition_time: float = 0.5  # Seconds between steps

    # Output
    capture_frames: bool = False  # Save each frame to disk
    capture_dir: Path = field(default_factory=lambda: Path(".companion/demo_frames"))

    # Recording
    record_cast: Path | None = None  # If set, save asciicast to this path
    record_gif: Path | None = None  # If set, convert cast to GIF
    gif_theme: str = "dracula"
    gif_font_size: int = 14
    gif_speed: float = 1.0

    # Behavior
    auto_advance: bool = True  # Auto-advance through steps
    interactive: bool = False  # Wait for keypress between steps
    headless: bool = False  # Don't write to terminal (recording only)


class DemoHarness:
    """Drives a CompanionRuntime through scripted demo scenarios.

    The harness:
    1. Creates a runtime pointed at the scenario's workspace
    2. Indexes the content
    3. For each step: moves cursor, waits, renders
    4. Optionally captures frames for screenshots
    5. Optionally records to asciicast / GIF
    """

    def __init__(self, config: DemoConfig | None = None) -> None:
        self.config = config or DemoConfig()
        self._renderer = TerminalRenderer(self.config.render)
        self._runtime: CompanionRuntime | None = None
        self._frame_count = 0
        self._recorder: AsciicastWriter | None = None

    def _is_recording(self) -> bool:
        return self._recorder is not None

    def _emit_frame(self, duration: float = 0.0) -> None:
        """Render current state and emit to all active outputs."""
        if not self.config.headless:
            self._renderer.render_to_terminal()

        if self._recorder:
            frame = self._renderer.render()
            self._recorder.write_frame(frame, duration=duration)

    async def run_scenario(self, scenario: DemoScenario) -> dict[str, Path]:
        """Run a complete demo scenario.

        Returns a dict of output paths:
            "cast": path to asciicast file (if recording)
            "gif": path to GIF file (if converting)
            "frames": list of frame paths (if capturing)
        """
        from remora_demo.companion.runtime import CompanionConfig, CompanionRuntime

        outputs: dict[str, Any] = {}

        # Set up recorder if configured
        if self.config.record_cast or self.config.record_gif:
            self._recorder = AsciicastWriter(
                cols=self.config.render.total_width,
                rows=self.config.render.total_height,
                title=f"Companion Demo — {scenario.name}",
            )

        # Create temp db for indexing
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "demo.db"
            workspace_path = Path(scenario.workspace_path)

            runtime_config = CompanionConfig(
                workspace_path=workspace_path,
                db_path=db_path,
                auto_index=True,
            )

            self._runtime = CompanionRuntime(runtime_config)

            try:
                # Setup terminal
                if not self.config.headless:
                    self._renderer.setup()

                # Show pre-narration
                if scenario.pre_narration:
                    narration_frame = self._build_narration_frame(scenario.name, scenario.pre_narration)
                    if self._recorder:
                        self._recorder.write_header_frame(narration_frame, duration=3.0)
                    if not self.config.headless:
                        sys.stdout.write(Ansi.CLEAR_SCREEN + Ansi.HOME + narration_frame)
                        sys.stdout.flush()
                    await asyncio.sleep(2.0)

                # Show indexing phase
                self._renderer.status.phase = "indexing"
                self._renderer.status.message = "Loading embedding model..."
                self._emit_frame(duration=1.0)

                # Start runtime (triggers indexing)
                await self._runtime.start()

                stats = self._runtime.indexer.store.stats()
                self._renderer.status.chunks_indexed = stats.get("total_chunks", 0)
                self._renderer.status.message = "Indexing complete"
                self._renderer.status.phase = "ready"
                self._emit_frame(duration=1.5)
                await asyncio.sleep(1.0)

                # Play each step
                for i, step in enumerate(scenario.steps):
                    self._renderer.status.phase = f"step {i + 1}/{len(scenario.steps)}"
                    self._renderer.status.message = step.caption
                    await self._play_step(step)

                    # Capture frame if configured
                    if self.config.capture_frames:
                        self._capture_frame(scenario.name, i)

                # Show post-narration
                if scenario.post_narration:
                    self._renderer.status.phase = "complete"
                    self._renderer.status.message = scenario.post_narration
                    self._emit_frame(duration=4.0)
                    await asyncio.sleep(3.0)

            finally:
                await self._runtime.stop()
                if not self.config.headless:
                    self._renderer.teardown()

        # Save recording outputs
        if self._recorder:
            self._recorder.write_finale(duration=2.0)

            cast_path = self.config.record_cast
            if cast_path is None and self.config.record_gif:
                # Need a temp cast file for GIF conversion
                cast_path = self.config.record_gif.with_suffix(".cast")

            if cast_path:
                saved = self._recorder.save(cast_path)
                outputs["cast"] = saved
                logger.info("Saved asciicast: %s", saved)

                if self.config.record_gif:
                    gif = AsciicastWriter.to_gif(
                        saved,
                        self.config.record_gif,
                        theme=self.config.gif_theme,
                        font_size=self.config.gif_font_size,
                        speed=self.config.gif_speed,
                    )
                    outputs["gif"] = gif
                    logger.info("Saved GIF: %s", gif)

        self._recorder = None
        return outputs

    async def _play_step(self, step: DemoStep) -> None:
        """Play a single demo step."""
        # Load file content for editor display
        file_path = Path(step.file)
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8", errors="replace")
            self._renderer.editor.lines = content.split("\n")
            self._renderer.editor.file_path = step.file
            self._renderer.editor.cursor_line = step.line

            # Auto-detect language
            if step.language:
                self._renderer.editor.language = step.language
            elif file_path.suffix == ".py":
                self._renderer.editor.language = "python"
            elif file_path.suffix in (".md", ".markdown"):
                self._renderer.editor.language = "markdown"
            else:
                self._renderer.editor.language = ""

            # Calculate scroll to center cursor
            content_height = self.config.render.content_height
            self._renderer.editor.scroll_offset = max(0, step.line - content_height // 3)

        # Show the editor update immediately (before agent results)
        self._renderer.status.agents_active = []
        self._emit_frame(duration=self.config.step_transition_time)
        await asyncio.sleep(self.config.step_transition_time)

        # Trigger cursor movement in the runtime
        self._renderer.status.agents_active = ["cursor_tracker"]
        self._emit_frame(duration=0.2)

        if self._runtime:
            await self._runtime.on_cursor_moved(step.file, step.line, step.col)

        # Wait for agent cascade with visual feedback
        await self._animate_agent_cascade()

        # Get sidebar content
        sidebar = await self._runtime.get_sidebar() if self._runtime else None
        self._renderer.sidebar.markdown = sidebar or ""

        # Final render with all results
        self._emit_frame(duration=step.pause_seconds)

        # Hold for viewing
        if self.config.interactive:
            _wait_for_key()
        else:
            await asyncio.sleep(step.pause_seconds)

    async def _animate_agent_cascade(self) -> None:
        """Animate the agent cascade in the status bar."""
        cascade_stages = [
            ["cursor_tracker", "context_extractor"],
            ["context_extractor", "embedding_searcher"],
            ["embedding_searcher", "connection_finder"],
            ["connection_finder", "sidebar_composer"],
        ]

        settle_per_stage = self.config.agent_settle_time / len(cascade_stages)

        for stage in cascade_stages:
            self._renderer.status.agents_active = stage

            # Get partial sidebar content if available
            if self._runtime:
                sidebar = await self._runtime.get_sidebar()
                if sidebar:
                    self._renderer.sidebar.markdown = sidebar

            self._emit_frame(duration=settle_per_stage)
            await asyncio.sleep(settle_per_stage)

        # Final settle
        self._renderer.status.agents_active = ["sidebar_composer"]
        await asyncio.sleep(0.2)
        self._renderer.status.agents_active = []

    def _build_narration_frame(self, title: str, text: str) -> str:
        """Build a narration screen as an ANSI string."""
        cfg = self.config.render
        lines = []
        lines.append("")
        lines.append(f"{Ansi.FG_MAUVE}{Ansi.BOLD}  {'━' * (cfg.total_width - 4)}{Ansi.RESET}")
        lines.append("")
        lines.append(f"{Ansi.FG_TEAL}{Ansi.BOLD}  {title}{Ansi.RESET}")
        lines.append("")

        wrapped = textwrap.wrap(text, width=cfg.total_width - 6)
        for line in wrapped:
            lines.append(f"{Ansi.FG_TEXT}  {line}{Ansi.RESET}")

        lines.append("")
        lines.append(f"{Ansi.FG_MAUVE}{Ansi.BOLD}  {'━' * (cfg.total_width - 4)}{Ansi.RESET}")
        lines.append("")
        lines.append(f"{Ansi.FG_DIM}  Press any key or wait...{Ansi.RESET}")

        return "\n".join(lines)

    def _show_narration(self, title: str, text: str) -> None:
        """Show a narration screen on the terminal."""
        frame = self._build_narration_frame(title, text)
        sys.stdout.write(Ansi.CLEAR_SCREEN)
        sys.stdout.write(Ansi.HOME)
        sys.stdout.write(frame)
        sys.stdout.flush()

    def _capture_frame(self, scenario_name: str, step_index: int) -> None:
        """Capture current frame to a plain-text file."""
        self.config.capture_dir.mkdir(parents=True, exist_ok=True)
        name = scenario_name.lower().replace(" ", "_")
        path = self.config.capture_dir / f"{name}_step_{step_index:02d}.txt"
        self._renderer.render_to_file(str(path))
        self._frame_count += 1

    async def run_all_scenarios(self, scenarios: list[DemoScenario]) -> list[dict[str, Path]]:
        """Run multiple scenarios in sequence.

        Returns a list of output dicts (one per scenario).
        """
        all_outputs = []
        for i, scenario in enumerate(scenarios):
            if i > 0:
                # Brief pause between scenarios
                if not self.config.headless:
                    sys.stdout.write(Ansi.CLEAR_SCREEN)
                    sys.stdout.write(Ansi.HOME)
                    sys.stdout.write(f"\n{Ansi.FG_DIM}  Next scenario in 2 seconds...{Ansi.RESET}\n")
                    sys.stdout.flush()
                await asyncio.sleep(2.0)

            outputs = await self.run_scenario(scenario)
            all_outputs.append(outputs)
        return all_outputs


def _wait_for_key() -> None:
    """Wait for a keypress (Unix only)."""
    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "q":
                raise KeyboardInterrupt
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except ImportError:
        input()
