"""Owns the Playwright lifecycle and creates isolated, persona-configured browser contexts."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Page, Request, Route, sync_playwright

import config
from security import is_domain_allowed, is_host_safe

log = logging.getLogger(__name__)


@dataclass
class PageMonitor:
    """Collects real console, page and network errors and blocked requests for one persona."""

    console_errors: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
    blocked_navigations: list[str] = field(default_factory=list)
    blocked_requests: int = 0
    _cursor: int = 0
    _net_cursor: int = 0

    def drain(self) -> list[str]:
        """Errors captured since the last drain call."""
        new = self.console_errors[self._cursor:] + self.network_errors[self._net_cursor:]
        self._cursor = len(self.console_errors)
        self._net_cursor = len(self.network_errors)
        return new[:10]


class BrowserManager:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None

    def __enter__(self) -> "BrowserManager":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=config.HEADLESS,
            args=["--disable-dev-shm-usage", "--no-first-run", "--disable-extensions"],
        )
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
        except Exception:  # pragma: no cover - best-effort cleanup
            log.exception("Failed closing browser")
        finally:
            self._browser = None
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:  # pragma: no cover
                log.exception("Failed stopping Playwright")
            self._pw = None

    def new_persona_context(
        self, persona: dict, viewport_name: str, allowed_domains: set[str]
    ) -> tuple[BrowserContext, Page, PageMonitor]:
        vp = config.VIEWPORTS.get(viewport_name, config.VIEWPORTS["Desktop"])
        zoom = max(1.0, min(float(persona.get("text_zoom") or 1.0), 3.0))
        # Browser zoom = fewer CSS pixels at a higher device pixel ratio, exactly like Ctrl/Cmd +.
        options: dict = {
            "viewport": {"width": int(vp["width"] / zoom), "height": int(vp["height"] / zoom)},
            "device_scale_factor": zoom,
            "is_mobile": vp["is_mobile"],
            "has_touch": vp["has_touch"],
            "accept_downloads": False,
            "java_script_enabled": True,
            "locale": "en-US",
            "ignore_https_errors": False,
            "service_workers": "block",
        }
        if vp["is_mobile"]:
            options["user_agent"] = config.MOBILE_USER_AGENT
        if persona.get("prefers_high_contrast"):
            options["contrast"] = "more"
            options["forced_colors"] = "active"
        if persona.get("interaction_mode") == "keyboard" or persona.get("patience", 5) <= 3:
            options["reduced_motion"] = "reduce"
        try:
            context = self._browser.new_context(**options)
        except TypeError:
            options.pop("contrast", None)
            context = self._browser.new_context(**options)

        context.set_default_timeout(config.ACTION_TIMEOUT_MS)
        context.set_default_navigation_timeout(config.NAVIGATION_TIMEOUT_MS)
        monitor = PageMonitor()

        def guard(route: Route, request: Request) -> None:
            parsed = urlparse(request.url)
            if parsed.scheme in ("data", "blob", "about"):
                route.continue_()
                return
            host = parsed.hostname
            if not is_host_safe(host):
                monitor.blocked_requests += 1
                if request.is_navigation_request():
                    monitor.blocked_navigations.append(f"{request.url} (private/unsafe address)")
                route.abort("blockedbyclient")
                return
            if (
                request.is_navigation_request()
                and request.frame.parent_frame is None
                and not is_domain_allowed(host, allowed_domains)
            ):
                monitor.blocked_navigations.append(request.url)
                route.abort("blockedbyclient")
                return
            route.continue_()

        context.route("**/*", guard)
        page = context.new_page()

        page.on("console", lambda msg: msg.type == "error" and monitor.console_errors.append(f"console: {msg.text[:200]}"))
        page.on("pageerror", lambda err: monitor.console_errors.append(f"js error: {str(err)[:200]}"))

        def on_response(resp) -> None:
            try:
                if resp.status >= 400 and resp.request.resource_type in ("document", "xhr", "fetch"):
                    monitor.network_errors.append(f"HTTP {resp.status} {resp.request.resource_type} {resp.url[:150]}")
            except Exception:
                pass

        def on_failed(req) -> None:
            failure = req.failure or ""
            if "blockedbyclient" in failure.lower() or "ERR_BLOCKED_BY_CLIENT" in failure:
                return
            if req.resource_type in ("document", "xhr", "fetch"):
                monitor.network_errors.append(f"request failed ({failure}) {req.url[:150]}")

        page.on("response", on_response)
        page.on("requestfailed", on_failed)
        page.on("dialog", lambda d: d.dismiss())
        return context, page, monitor
