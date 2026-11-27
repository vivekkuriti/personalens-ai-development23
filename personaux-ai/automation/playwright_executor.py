"""Executes validated persona actions in a real browser, honoring each persona's interaction mode."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

import config
from automation.dom_inspector import DomSnapshot
from security import is_navigation_allowed

ALLOWED_KEYS = {
    "Tab", "Shift+Tab", "Enter", "Space", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight",
    "PageDown", "PageUp", "Home", "End", "Backspace",
}
UNSAFE_PATTERNS = re.compile(
    r"\b(buy( now)?|purchase|place (your )?order|complete (the )?order|pay( now)?|confirm payment|checkout|"
    r"add payment|submit payment|donate|delete( my)? account|close( my)? account|deactivate|"
    r"remove account|cancel (my )?subscription|unsubscribe|transfer funds|send money)\b",
    re.I,
)
MAX_TAB_PRESSES = 80


@dataclass
class ActionResult:
    success: bool
    error: str | None = None
    detail: str = ""
    navigated: bool = False
    load_time_ms: int | None = None
    blocked: bool = False
    keyboard_unreachable: bool = False
    tab_presses: int = 0
    extra: dict = field(default_factory=dict)


class PlaywrightExecutor:
    def __init__(self, page: Page, persona: dict, allowed_domains: set[str]) -> None:
        self.page = page
        self.persona = persona
        self.allowed_domains = allowed_domains
        self.mode = persona.get("interaction_mode", "mouse")

    # ---------- helpers ----------

    def _wait_after_interaction(self, url_before: str) -> tuple[bool, int | None]:
        start = time.monotonic()
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=config.NAVIGATION_TIMEOUT_MS)
        except PlaywrightTimeout:
            pass
        try:
            self.page.wait_for_load_state("load", timeout=6000)
        except PlaywrightTimeout:
            pass
        try:
            self.page.wait_for_load_state("networkidle", timeout=2500)
        except PlaywrightTimeout:
            pass
        navigated = self.page.url.split("#")[0] != url_before.split("#")[0]
        load_ms = None
        if navigated:
            load_ms = self.navigation_timing() or int((time.monotonic() - start) * 1000)
        return navigated, load_ms

    def navigation_timing(self) -> int | None:
        try:
            value = self.page.evaluate(
                "() => { const n = performance.getEntriesByType('navigation')[0];"
                " return n ? Math.round((n.loadEventEnd || n.domContentLoadedEventEnd || n.responseEnd) - n.startTime) : null; }"
            )
            return int(value) if value and value > 0 else None
        except PlaywrightError:
            return None

    def _locate(self, element_id: int | None, target: str, dom: DomSnapshot) -> Locator | None:
        if element_id is not None and dom.element(element_id):
            loc = self.page.locator(f'[data-pux-id="{element_id}"]')
            if loc.count() > 0:
                return loc.first
        target = (target or "").strip().strip('"')
        if not target:
            return None
        candidates = [
            self.page.get_by_role("button", name=target),
            self.page.get_by_role("link", name=target),
            self.page.get_by_label(target),
            self.page.get_by_placeholder(target),
            self.page.get_by_text(target, exact=False),
        ]
        for loc in candidates:
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    return loc.first
            except PlaywrightError:
                continue
        return None

    def _is_unsafe(self, *texts: str) -> bool:
        return any(t and UNSAFE_PATTERNS.search(t) for t in texts)

    def _focus_by_keyboard(self, locator: Locator) -> int | None:
        """Press Tab like a real keyboard user until the target is focused. Returns presses or None."""
        handle = locator.element_handle()
        if handle is None:
            return None
        for presses in range(1, MAX_TAB_PRESSES + 1):
            self.page.keyboard.press("Tab")
            focused = self.page.evaluate(
                "(el) => { const a = document.activeElement; return !!a && (a === el || el.contains(a) || a.contains(el)); }",
                handle,
            )
            if focused:
                return presses
        return None

    def _resolve_value(self, element: dict | None, value: str) -> str:
        """Always substitute dedicated test credentials so real data is never entered."""
        if not element:
            return value
        hint = " ".join(
            [element.get("type", ""), element.get("name", ""), element.get("field_name", ""),
             element.get("placeholder", ""), element.get("autocomplete", "")]
        ).lower()
        if element.get("type") == "password" or "password" in hint:
            return config.TEST_ACCOUNT_PASSWORD
        if element.get("type") == "email" or "email" in hint or "e-mail" in hint:
            return config.TEST_ACCOUNT_EMAIL
        if element.get("type") == "tel" or "phone" in hint:
            return config.TEST_ACCOUNT_PHONE
        if any(k in hint for k in ("card", "cvv", "cvc", "iban", "ssn", "social security")):
            return ""
        return value

    # ---------- main entry ----------

    def execute(self, action: str, element_id: int | None, target: str, value: str, dom: DomSnapshot) -> ActionResult:
        url_before = self.page.url
        element = dom.element(element_id)
        try:
            if action == "navigate":
                return self._navigate(value or target)
            if action == "back":
                self.page.go_back(wait_until="domcontentloaded")
                navigated, load = self._wait_after_interaction(url_before)
                return ActionResult(True, detail="Went back", navigated=navigated, load_time_ms=load)
            if action == "scroll":
                return self._scroll(value)
            if action == "wait":
                ms = 1500
                try:
                    ms = max(300, min(int(float(value or 1.5) * 1000) if float(value or 1.5) < 30 else int(value), 5000))
                except ValueError:
                    pass
                self.page.wait_for_timeout(ms)
                return ActionResult(True, detail=f"Waited {ms} ms")
            if action == "press":
                key = (value or target or "").strip()
                key = {"Return": "Enter", "Esc": "Escape", " ": "Space"}.get(key, key)
                if key not in ALLOWED_KEYS:
                    return ActionResult(False, error=f"Key '{key}' is not permitted")
                self.page.keyboard.press(key)
                navigated, load = self._wait_after_interaction(url_before)
                return ActionResult(True, detail=f"Pressed {key}", navigated=navigated, load_time_ms=load)

            locator = self._locate(element_id, target, dom)
            if locator is None:
                return ActionResult(False, error=f"Target not found on page: {target or element_id}")
            label = (element or {}).get("name") or target
            if action == "click" and self._is_unsafe(label, target, (element or {}).get("href", "")):
                return ActionResult(False, blocked=True, error=f"Blocked by safety policy (irreversible action): '{label}'")

            if action == "click":
                return self._click(locator, element, url_before)
            if action == "fill":
                return self._fill(locator, element, value)
            if action == "select":
                return self._select(locator, value)
            return ActionResult(False, error=f"Unsupported action '{action}'")
        except PlaywrightTimeout as exc:
            return ActionResult(False, error=f"Timed out: {str(exc).splitlines()[0][:200]}")
        except PlaywrightError as exc:
            msg = str(exc).splitlines()[0][:200]
            if "ERR_BLOCKED_BY_CLIENT" in msg:
                return ActionResult(False, blocked=True, error="Navigation blocked: outside the approved domain")
            return ActionResult(False, error=msg)

    def _navigate(self, url: str) -> ActionResult:
        if not url:
            return ActionResult(False, error="No URL provided for navigate")
        if url.startswith("/"):
            from urllib.parse import urljoin

            url = urljoin(self.page.url, url)
        if not is_navigation_allowed(url, self.allowed_domains):
            return ActionResult(False, blocked=True, error=f"Navigation to {url} blocked: outside approved domain")
        start = time.monotonic()
        response = self.page.goto(url, wait_until="domcontentloaded")
        try:
            self.page.wait_for_load_state("load", timeout=8000)
        except PlaywrightTimeout:
            pass
        load = self.navigation_timing() or int((time.monotonic() - start) * 1000)
        status = response.status if response else None
        if status and status >= 400:
            return ActionResult(False, error=f"Page returned HTTP {status}", navigated=True, load_time_ms=load,
                                extra={"http_status": status})
        return ActionResult(True, detail=f"Loaded {url} (HTTP {status})", navigated=True, load_time_ms=load,
                            extra={"http_status": status})

    def _scroll(self, value: str) -> ActionResult:
        direction = -1 if (value or "").lower() in ("up", "-1", "top") else 1
        if self.mode == "keyboard":
            self.page.keyboard.press("PageDown" if direction > 0 else "PageUp")
        else:
            self.page.mouse.wheel(0, 650 * direction)
        self.page.wait_for_timeout(400)
        return ActionResult(True, detail=f"Scrolled {'down' if direction > 0 else 'up'}")

    def _click(self, locator: Locator, element: dict | None, url_before: str) -> ActionResult:
        if self.mode == "keyboard":
            presses = self._focus_by_keyboard(locator)
            if presses is None:
                return ActionResult(False, keyboard_unreachable=True,
                                    error=f"Element could not be reached with the Tab key after {MAX_TAB_PRESSES} presses")
            role = (element or {}).get("role")
            self.page.keyboard.press("Space" if role in ("checkbox", "radio", "switch") else "Enter")
            navigated, load = self._wait_after_interaction(url_before)
            return ActionResult(True, detail=f"Focused via {presses} Tab presses and activated with keyboard",
                                navigated=navigated, load_time_ms=load, tab_presses=presses)
        locator.scroll_into_view_if_needed(timeout=config.ACTION_TIMEOUT_MS)
        locator.click(timeout=config.ACTION_TIMEOUT_MS)
        navigated, load = self._wait_after_interaction(url_before)
        return ActionResult(True, detail="Clicked", navigated=navigated, load_time_ms=load)

    def _fill(self, locator: Locator, element: dict | None, value: str) -> ActionResult:
        real_value = self._resolve_value(element, value or "")
        if real_value == "" and value:
            return ActionResult(False, blocked=True, error="Blocked by safety policy: sensitive payment/identity field")
        masked = "********" if element and (element.get("type") == "password") else real_value
        if self.mode == "keyboard":
            presses = self._focus_by_keyboard(locator)
            if presses is None:
                return ActionResult(False, keyboard_unreachable=True,
                                    error="Field could not be reached with the Tab key")
            self.page.keyboard.press("Control+A")
            self.page.keyboard.type(real_value, delay=15)
            return ActionResult(True, detail=f"Tabbed {presses}x and typed '{masked}'", tab_presses=presses)
        locator.scroll_into_view_if_needed(timeout=config.ACTION_TIMEOUT_MS)
        locator.fill(real_value, timeout=config.ACTION_TIMEOUT_MS)
        if self.mode == "mixed":
            locator.dispatch_event("change")
        return ActionResult(True, detail=f"Filled '{masked}'")

    def _select(self, locator: Locator, value: str) -> ActionResult:
        if self.mode == "keyboard":
            presses = self._focus_by_keyboard(locator)
            if presses is None:
                return ActionResult(False, keyboard_unreachable=True, error="Dropdown not reachable with Tab key")
        try:
            locator.select_option(label=value, timeout=config.ACTION_TIMEOUT_MS)
        except PlaywrightError:
            locator.select_option(value=value, timeout=config.ACTION_TIMEOUT_MS)
        return ActionResult(True, detail=f"Selected '{value}'")
