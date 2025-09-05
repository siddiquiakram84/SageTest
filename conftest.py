# conftest.py
import os
import json
import time
import logging
import tempfile
from dataclasses import dataclass
from typing import Generator, Optional, Protocol, Dict, Any
from pathlib import Path

import pytest
import allure
from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as GeckoService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager

from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.common.exceptions import WebDriverException

# Import your self-healing module (rename/move file to core/self_heal.py)
try:
    from core.self_heal import find_with_healing, HEAL_LOG
except Exception:
    # Fallback so conftest still loads during incremental development.
    HEAL_LOG = "healing_log.json"
    def find_with_healing(driver, by, locator, **kwargs):
        return driver.find_element(by, locator)

# Optional upload to S3
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except Exception:
    boto3 = None

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

ROOT = Path(__file__).resolve().parent

# --------------------
# Configuration objects
# --------------------
@dataclass(frozen=True)
class TestConfig:
    base_url: str
    browser: str
    headless: bool
    record_logs: bool
    upload_s3: bool
    implicit_wait: int = 5
    page_load_timeout: int = 30
    screenshot_dir: Path = ROOT / "allure-results" / "screenshots"

# --------------------
# Driver factory protocol
# --------------------
class DriverFactory(Protocol):
    def create(self, config: TestConfig) -> WebDriver:
        ...

# --------------------
# Concrete factories
# --------------------
class ChromeFactory:
    def create(self, config: TestConfig) -> WebDriver:
        opts = ChromeOptions()
        # Use new headless mode where supported
        if config.headless:
            # Chrome changed headless flags across versions; using modern one
            try:
                opts.add_argument("--headless=new")
            except Exception:
                opts.add_argument("--headless")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        # disable popups, disable-extensions etc (tweak for your CI)
        opts.add_argument("--disable-extensions")
        # Create service & driver
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        driver.set_page_load_timeout(config.page_load_timeout)
        driver.implicitly_wait(config.implicit_wait)
        return driver

class FirefoxFactory:
    def create(self, config: TestConfig) -> WebDriver:
        opts = FirefoxOptions()
        if config.headless:
            opts.add_argument("-headless")
        service = GeckoService(GeckoDriverManager().install())
        driver = webdriver.Firefox(service=service, options=opts)
        driver.set_page_load_timeout(config.page_load_timeout)
        driver.implicitly_wait(config.implicit_wait)
        return driver

# --------------------
# Helper utilities
# --------------------
def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def save_json(path: Path, data: Dict[str, Any]):
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def attach_file_to_allure(name: str, file_path: Path, attachment_type=None):
    if not file_path.exists():
        return
    with file_path.open("rb") as f:
        content = f.read()
        if attachment_type is None:
            # default to text if small or binary attach raw
            attachment_type = allure.attachment_type.TEXT
        allure.attach(content, name=name, attachment_type=attachment_type)

# --------------------
# Pytest cli options
# --------------------
def pytest_addoption(parser):
    parser.addoption("--base-url", action="store", default=os.getenv("BASE_URL", "https://www.saucedemo.com"), help="Base URL for tests")
    parser.addoption("--browser", action="store", default=os.getenv("BROWSER", "chrome"), help="Browser: chrome or firefox")
    parser.addoption("--headless", action="store_true", default=os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes"), help="Run in headless mode")
    parser.addoption("--record-logs", action="store_true", default=os.getenv("RECORD_LOGS", "true").lower() in ("true", "1", "yes"), help="Record browser console logs and attach on failure")
    parser.addoption("--upload-s3", action="store_true", default=os.getenv("UPLOAD_S3", "false").lower() in ("true", "1", "yes"), help="Upload artifacts to S3 at end of session")

# --------------------
# Global fixtures / objects
# --------------------
@pytest.fixture(scope="session")
def test_config(pytestconfig) -> TestConfig:
    base_url = pytestconfig.getoption("base_url")
    browser = pytestconfig.getoption("browser").lower()
    headless = pytestconfig.getoption("headless")
    record_logs = pytestconfig.getoption("record_logs")
    upload_s3 = pytestconfig.getoption("upload_s3")
    cfg = TestConfig(
        base_url=base_url,
        browser=browser,
        headless=headless,
        record_logs=record_logs,
        upload_s3=upload_s3,
    )
    ensure_dir(cfg.screenshot_dir)
    return cfg

@pytest.fixture(scope="session")
def logger() -> logging.Logger:
    log = logging.getLogger("sagetest")
    if not log.handlers:
        log.setLevel(logging.INFO)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(ch)
    return log

# --------------------
# WebDriver fixture (function-scoped)
# --------------------
@pytest.fixture(scope="function")
def driver(test_config: TestConfig, logger: logging.Logger) -> Generator[WebDriver, None, None]:
    """
    Creates a webdriver for each test function. You can change the scope to 'session'
    if you want a single driver per worker — but function scope is safer and more isolated.
    """
    factory: DriverFactory
    if test_config.browser == "chrome":
        factory = ChromeFactory()
    elif test_config.browser == "firefox":
        factory = FirefoxFactory()
    else:
        raise ValueError(f"Unsupported browser: {test_config.browser}")

    try:
        logger.info(f"Creating webdriver for browser={test_config.browser} headless={test_config.headless}")
        drv = factory.create(test_config)
    except WebDriverException as e:
        logger.exception("Failed to create webdriver")
        raise

    # Provide helper method to use self-heal transparently in tests/pages:
    def find_with_auto_heal(by, locator, *, heal=True, **kwargs):
        if heal:
            return find_with_healing(drv, by, locator, **kwargs)
        return drv.find_element(by, locator)

    # Monkey-patch driver for convenience (safe for test-time)
    setattr(drv, "find_with_heal", find_with_auto_heal)

    yield drv

    # Teardown
    try:
        drv.quit()
    except Exception:
        logger.exception("Error quitting driver")

# --------------------
# Base URL fixture
# --------------------
@pytest.fixture(scope="function")
def base_url(test_config: TestConfig) -> str:
    return test_config.base_url

# --------------------
# Test metadata collector (per-test)
# --------------------
@pytest.fixture(scope="function", autouse=True)
def test_metadata(request, tmp_path, logger):
    meta = {"nodeid": request.node.nodeid, "start_time": time.time(), "attachments": []}
    # store meta on node for access in hooks
    request.node._sagetest_meta = meta  # type: ignore[attr-defined]
    yield meta
    meta["end_time"] = time.time()
    # Save summary for this test run (not global)
    summary_path = tmp_path / "test_summary.json"
    save_json(summary_path, meta)
    logger.debug(f"Saved per-test summary to {summary_path}")

# --------------------
# Pytest hooks - attach logs and artifacts
# --------------------
def _capture_screenshot(driver: WebDriver, dest: Path) -> Optional[Path]:
    try:
        driver.save_screenshot(str(dest))
        return dest
    except Exception:
        return None

def _capture_page_source(driver: WebDriver, dest: Path) -> Optional[Path]:
    try:
        src = driver.page_source
        dest.write_text(src, encoding="utf-8")
        return dest
    except Exception:
        return None

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Attach artifacts to Allure on test failure (screenshot, page source, healing log, browser console).
    """
    outcome = yield
    rep = outcome.get_result()

    # only care about call (test body) phase
    if rep.when != "call":
        return

    meta = getattr(item, "_sagetest_meta", {})
    driver: Optional[WebDriver] = item.funcargs.get("driver", None)
    logger: Optional[logging.Logger] = item.funcargs.get("logger", None)

    # On failure, capture artifacts and attach to Allure
    if rep.failed:
        ts = int(time.time() * 1000)
        # screenshot
        if driver is not None:
            screenshot_file = Path(tempfile.gettempdir()) / f"screenshot-{ts}.png"
            ss_path = _capture_screenshot(driver, screenshot_file)
            if ss_path:
                try:
                    with ss_path.open("rb") as f:
                        allure.attach(f.read(), name="screenshot", attachment_type=allure.attachment_type.PNG)
                except Exception:
                    pass

            # page source
            ps_file = Path(tempfile.gettempdir()) / f"page_{ts}.html"
            ps_path = _capture_page_source(driver, ps_file)
            if ps_path:
                try:
                    with ps_path.open("rb") as f:
                        allure.attach(f.read(), name="page_source", attachment_type=allure.attachment_type.HTML)
                except Exception:
                    pass

            # healing log (if present)
            heal_log = Path(HEAL_LOG)
            if heal_log.exists():
                try:
                    with heal_log.open("rb") as f:
                        allure.attach(f.read(), name="healing_log", attachment_type=allure.attachment_type.TEXT)
                except Exception:
                    pass

        # Browser console logs (Chrome)
        if driver is not None and hasattr(driver, "get_log"):
            try:
                logs = driver.get_log("browser")
                if logs:
                    allure.attach(json.dumps(logs, indent=2, default=str), name="browser_console", attachment_type=allure.attachment_type.JSON)
            except Exception:
                # some drivers do not support get_log or log level config
                pass

    # Always attach test metadata saved by fixture
    try:
        if meta:
            allure.attach(json.dumps(meta, indent=2), name="test_metadata", attachment_type=allure.attachment_type.JSON)
    except Exception:
        pass

# --------------------
# Session end hook - upload artifacts if needed
# --------------------
def pytest_sessionfinish(session, exitstatus):
    """
    Optionally upload artifacts (healing log, allure-results) to S3 if enabled.
    Uses env vars: S3_BUCKET, S3_PREFIX (optional).
    """
    try:
        cfg = TestConfig(
            base_url=os.getenv("BASE_URL", "https://www.saucedemo.com"),
            browser=os.getenv("BROWSER", "chrome"),
            headless=os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes"),
            record_logs=os.getenv("RECORD_LOGS", "true").lower() in ("true", "1", "yes"),
            upload_s3=os.getenv("UPLOAD_S3", "false").lower() in ("true", "1", "yes"),
        )
    except Exception:
        cfg = None

    # If configured and boto3 is available, upload healing log + allure artifacts
    if cfg and cfg.upload_s3 and boto3:
        s3_bucket = os.getenv("S3_BUCKET")
        s3_prefix = os.getenv("S3_PREFIX", "sagetest")
        if not s3_bucket:
            # pytest.warns is not available here; log a warning using session
            try:
                session.config.warn("S3:MissingBucket", "UPLOAD_S3 set but S3_BUCKET not provided.")
            except Exception:
                pass
            return

        client = boto3.client("s3")
        # upload healing log
        heal = Path(HEAL_LOG)
        try:
            if heal.exists():
                key = f"{s3_prefix}/healing_log/{heal.name}"
                client.upload_file(str(heal), s3_bucket, key)
        except (BotoCoreError, ClientError, Exception) as e:
            try:
                session.config.warn("S3:UploadFailed", f"Failed to upload healing log: {e}")
            except Exception:
                pass

        # upload allure-results (if present)
        allure_dir = ROOT / "allure-results"
        if allure_dir.exists():
            for p in allure_dir.rglob("*"):
                if p.is_file():
                    # build key preserving tree under allure-results
                    rel = p.relative_to(allure_dir)
                    key = f"{s3_prefix}/allure/{rel}"
                    try:
                        client.upload_file(str(p), s3_bucket, key)
                    except Exception as e:
                        try:
                            session.config.warn("S3:PartialUpload", f"Failed uploading {p}: {e}")
                        except Exception:
                            pass

# --------------------
# Convenience: register custom markers and config
# --------------------
def pytest_configure(config):
    # Register markers used across your suites
    config.addinivalue_line("markers", "slow: mark test as slow")
    config.addinivalue_line("markers", "smoke: mark test as smoke")
    # Ensure allure-results dir exists
    ensure_dir(Path("allure-results"))

# End of conftest.py
