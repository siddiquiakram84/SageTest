# core/driver_factory.py
"""
Driver factory that returns configured Selenium or Selenium-Wire WebDriver.

Usage:
    from core.driver_factory import create_driver, TestConfig
    cfg = TestConfig(base_url="...", browser="chrome", headless=True, ...)
    driver = create_driver(cfg)
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

# try to import selenium-wire
try:
    from seleniumwire import webdriver as wire_webdriver  # type: ignore
    SELENIUM_WIRE_AVAILABLE = True
except Exception:
    SELENIUM_WIRE_AVAILABLE = False

from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as GeckoService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions

logger = logging.getLogger("sagetest.driver")

@dataclass(frozen=True)
class TestConfig:
    base_url: str
    browser: str = "chrome"
    headless: bool = True
    implicit_wait: int = 5
    page_load_timeout: int = 30
    seleniumwire_options: Optional[dict] = None  # passed when selenium-wire used

def _attach_dump_network(driver: WebDriver, dest_dir: Path):
    """
    Attach a dump_network method to driver that creates a network_<ts>.json
    (works for selenium-wire drivers). Best-effort; silent on failure.
    """
    def dump_network(to_path: Path):
        try:
            to_path.parent.mkdir(parents=True, exist_ok=True)
            items = []
            # selenium-wire driver has .requests
            for r in getattr(driver, "requests", []):
                try:
                    item = {
                        "method": r.method,
                        "url": r.url,
                        "status_code": r.response.status_code if r.response else None,
                        "request_headers": dict(r.headers),
                        "response_headers": dict(r.response.headers) if r.response else None,
                        "response_body": None
                    }
                    if r.response and r.response.body and len(r.response.body) < 200000:
                        try:
                            item["response_body"] = r.response.body.decode("utf-8", errors="replace")
                        except Exception:
                            item["response_body"] = repr(r.response.body)
                    items.append(item)
                except Exception:
                    continue
            to_path.write_text(json.dumps(items, indent=2), encoding="utf-8")
            return to_path
        except Exception as e:
            logger.exception("dump_network failed: %s", e)
            return None
    setattr(driver, "dump_network", dump_network)
    return driver

def create_driver(cfg: TestConfig) -> WebDriver:
    """
    Create and return a WebDriver according to cfg.
    If selenium-wire is available, create a selenium-wire Chrome to capture network.
    """
    browser = cfg.browser.lower()
    if browser == "chrome":
        opts = ChromeOptions()
        if cfg.headless:
            try:
                opts.add_argument("--headless=new")
            except Exception:
                opts.add_argument("--headless")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-extensions")
        service = ChromeService(ChromeDriverManager().install())
        if SELENIUM_WIRE_AVAILABLE:
            sw_opts = cfg.seleniumwire_options or {"enable_har": True}
            driver = wire_webdriver.Chrome(service=service, options=opts, seleniumwire_options=sw_opts)
            # attach dump helper
            _attach_dump_network(driver, Path.cwd())
        else:
            driver = webdriver.Chrome(service=service, options=opts)
    elif browser == "firefox":
        opts = FirefoxOptions()
        if cfg.headless:
            opts.add_argument("-headless")
        service = GeckoService(GeckoDriverManager().install())
        driver = webdriver.Firefox(service=service, options=opts)
    else:
        raise ValueError(f"Unsupported browser: {browser}")

    if cfg.page_load_timeout:
        try:
            driver.set_page_load_timeout(cfg.page_load_timeout)
        except Exception:
            pass
    if cfg.implicit_wait:
        try:
            driver.implicitly_wait(cfg.implicit_wait)
        except Exception:
            pass

    logger.info("Created driver: %s (headless=%s)", browser, cfg.headless)
    return driver
