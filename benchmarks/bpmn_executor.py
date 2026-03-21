"""
Headless bpmn.io executor for the benchmark runner.

Launches a headless Chromium browser via Playwright, loads bpmn_headless.html,
and applies frontend-format actions to produce BPMN 2.0 XML — the exact same
pipeline as the frontend task.js canvas, but without a visible UI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from playwright.async_api import Browser, Playwright as PlaywrightType

_HTML_PATH = Path(__file__).parent / "bpmn_headless.html"


class BpmnIoExecutor:
    """
    Headless bpmn.io session — one Browser shared across all benchmark runs;
    each modelling job gets its own isolated page (and therefore a fresh
    bpmn-js modeler instance).

    Usage:
        async with async_playwright() as pw:
            executor = await BpmnIoExecutor.create(pw)
            try:
                xml = await executor.execute(actions)
            finally:
                await executor.close()
    """

    def __init__(self, browser: Browser) -> None:
        self._browser = browser

    @classmethod
    async def create(cls, playwright: PlaywrightType) -> "BpmnIoExecutor":
        """Launch a headless Chromium browser and return an executor instance."""
        if not _HTML_PATH.exists():
            raise FileNotFoundError(
                f"Headless HTML executor not found: {_HTML_PATH}\n"
                "Make sure benchmarks/bpmn_headless.html exists."
            )
        browser = await playwright.chromium.launch(headless=True)
        return cls(browser)

    async def execute(self, actions: List[Dict[str, Any]]) -> str:
        """
        Apply *actions* to a fresh bpmn.io modeler and return the BPMN 2.0 XML.

        Actions must be in the frontend format produced by
        BenchmarkRunner._convert_actions() — keys: elementId, elementType,
        parentId, sourceId, targetId, isExpanded, …

        Raises:
            RuntimeError: if bpmn.io returns an empty result.
        """
        page = await self._browser.new_page()
        try:
            def _on_console(msg) -> None:
                if msg.type in ("error", "warning", "warn"):
                    print(f"  [bpmn.io:{msg.type}] {msg.text}", flush=True)

            page.on("console", _on_console)
            page.set_default_timeout(60_000)

            await page.goto(_HTML_PATH.as_uri(), wait_until="domcontentloaded")
            await page.wait_for_function("window.isReady === true", timeout=30_000)

            xml: str | None = await page.evaluate(
                "(actions) => window.applyActionsAndGetXml(actions)",
                actions,
            )
            if not xml:
                raise RuntimeError("bpmn.io returned empty XML")
            return xml
        finally:
            await page.close()

    async def close(self) -> None:
        """Close the underlying browser."""
        await self._browser.close()