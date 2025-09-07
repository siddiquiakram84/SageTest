# conftest.py
"""
Conftest for SageTest. Assumes this file lives in SageTest1/aut/.
Writes artifacts into aut/test_report/<TS>/ and uses core.* modules when available.
"""
import os
import json
import time
import logging
from dataclasses import dataclass
from typing import Generator, Optional, Protocol, Dict, Any
from pathlib import Path

import pytest
import allure

# try using core.driver_factory and core.logger
try:
    from core import driver_factory as core_driver_factory
except Exception:
    core_driver_factory = None

try:
    from core.logger import get_logger as core_get_logger
except Exception:
    core_get_logger = None

# self-heal fallback
try:
    from core.self_heal import find_with_healing, HEAL_LOG
except Exception:
    HEAL_LOG = "healing_log.json"
    def find_with_healing(driver, by, locator, **kwargs):
        return driver.find_element(by, locator)

# IMPORTANT PATHS: conftest.py lives inside aut/, so:
THIS_FILE = Path(__file__).resolve()
AUT_ROOT = THIS_FILE.parent              # <project>/aut
PROJECT_ROOT = AUT_ROOT.parent           # <project>
# Timestamp exported by runner (runner.py sets SAGETEST_TS)
TS = os.getenv("SAGETEST_TS", time.strftime("%Y%m%d_%H%M%S"))

# Single-run artifact directories under aut/
TEST_REPORT_DIR = AUT_ROOT / "test_report" / TS
SCREENSHOT_DIR = TEST_REPORT_DIR / "screenshots"
NETWORK_DIR = TEST_REPORT_DIR / "network"
LOG_DIR = AUT_ROOT / "logs" / TS
METADATA_FILE = AUT_ROOT / "report_metadata.json"

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def save_json(path: Path, data: Dict[str, Any]):
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

@dataclass(frozen=True)
class TestConfig:
    base_url: str
    browser: str
    headless: bool
    record_logs: bool
    upload_s3: bool
    implicit_wait: int = 5
    page_load_timeout: int = 30
    screenshot_dir: Path = SCREENSHOT_DIR
    network_dir: Path = NETWORK_DIR

# configure logging (prefer core.get_logger)
def configure_logging():
    ensure_dir(LOG_DIR)
    if core_get_logger:
        try:
            return core_get_logger(LOG_DIR, TS)
        except Exception:
            pass
    # fallback simple logger: console + json-lines file
    log_path = LOG_DIR / "suite.log"
    logger = logging.getLogger("sagetest")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)
    fh = logging.FileHandler(str(log_path), encoding="utf-8")
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            p = {"time": time.time(), "level": record.levelname, "msg": record.getMessage()}
            if record.exc_info:
                p["exc"] = self.formatException(record.exc_info)
            return json.dumps(p)
    fh.setFormatter(JsonFormatter())
    logger.addHandler(fh)
    logger.info(f"Logging initialized: {log_path}")
    return logger

# copy top-level metadata into run folder for traceability
def _copy_run_metadata():
    if METADATA_FILE.exists():
        try:
            content = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
            save_json(TEST_REPORT_DIR / "report_metadata.json", content)
        except Exception:
            pass

# pytest options
def pytest_addoption(parser):
    parser.addoption("--base-url", action="store", default=os.getenv("BASE_URL", "https://www.saucedemo.com"))
    parser.addoption("--browser", action="store", default=os.getenv("BROWSER", "chrome"))
    parser.addoption("--headless", action="store_true", default=os.getenv("HEADLESS", "true").lower() in ("true","1","yes"))
    parser.addoption("--record-logs", action="store_true", default=os.getenv("RECORD_LOGS", "true").lower() in ("true","1","yes"))
    parser.addoption("--upload-s3", action="store_true", default=os.getenv("UPLOAD_S3", "false").lower() in ("true","1","yes"))

# ensure run directories exist immediately so pytest attachments won't fail
ensure_dir(TEST_REPORT_DIR)
ensure_dir(SCREENSHOT_DIR)
ensure_dir(NETWORK_DIR)
ensure_dir(LOG_DIR)
_copy_run_metadata()

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
    ensure_dir(cfg.network_dir)
    return cfg

@pytest.fixture(scope="session")
def logger():
    return configure_logging()

@pytest.fixture(scope="function")
def driver(test_config: TestConfig, logger: logging.Logger) -> Generator:
    # prefer core.driver_factory.create_driver
    drv = None
    if core_driver_factory and hasattr(core_driver_factory, "create_driver"):
        try:
            drv = core_driver_factory.create_driver(core_driver_factory.TestConfig(
                base_url=test_config.base_url,
                browser=test_config.browser,
                headless=test_config.headless,
                implicit_wait=test_config.implicit_wait,
                page_load_timeout=test_config.page_load_timeout,
                seleniumwire_options=getattr(core_driver_factory, "SELENIUMWIRE_DEFAULTS", None)
            ))
        except Exception:
            drv = None

    if drv is None:
        # minimal fallback factories (chrome)
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service as ChromeService
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        opts = ChromeOptions()
        if test_config.headless:
            try:
                opts.add_argument("--headless=new")
            except Exception:
                opts.add_argument("--headless")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        service = ChromeService(ChromeDriverManager().install())
        drv = webdriver.Chrome(service=service, options=opts)

    # helper to use self-heal
    def find_with_auto_heal(by, locator, *, heal=True, **kwargs):
        if heal:
            return find_with_healing(drv, by, locator, **kwargs)
        return drv.find_element(by, locator)
    setattr(drv, "find_with_heal", find_with_auto_heal)

    # attach dump_network helper if missing
    if not hasattr(drv, "dump_network"):
        def dump_network(to_path: Path):
            try:
                items = []
                for r in getattr(drv, "requests", []):
                    try:
                        it = {"method": r.method, "url": r.url, "status_code": r.response.status_code if r.response else None}
                        if r.response and getattr(r.response, "body", None) and len(r.response.body) < 200000:
                            try:
                                it["response_body"] = r.response.body.decode("utf-8", errors="replace")
                            except Exception:
                                it["response_body"] = repr(r.response.body)
                        items.append(it)
                    except Exception:
                        continue
                to_path.parent.mkdir(parents=True, exist_ok=True)
                to_path.write_text(json.dumps(items, indent=2), encoding="utf-8")
                return to_path
            except Exception:
                return None
        setattr(drv, "dump_network", dump_network)

    yield drv

    try:
        drv.quit()
    except Exception:
        logger.exception("Error quitting driver")

@pytest.fixture(scope="function", autouse=True)
def test_metadata(request, tmp_path, logger):
    meta = {"nodeid": request.node.nodeid, "start_time": time.time(), "attachments": []}
    request.node._sagetest_meta = meta  # type: ignore
    yield meta
    meta["end_time"] = time.time()
    summary_path = tmp_path / "test_summary.json"
    save_json(summary_path, meta)
    logger.debug(f"Saved per-test summary to {summary_path}")

# helpers
def _capture_screenshot(driver, dest: Path):
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(str(dest))
        return dest
    except Exception:
        return None

def _capture_page_source(driver, dest: Path):
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(driver.page_source, encoding="utf-8")
        return dest
    except Exception:
        return None

# Attach artifacts to Allure on test failure
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when != "call":
        return

    meta = getattr(item, "_sagetest_meta", {})
    driver = item.funcargs.get("driver", None)
    logger = item.funcargs.get("logger", None)

    if rep.failed:
        ts_ms = int(time.time() * 1000)
        # screenshot
        if driver is not None:
            ss_file = SCREENSHOT_DIR / f"screenshot_{ts_ms}.png"
            ss = _capture_screenshot(driver, ss_file)
            if ss:
                try:
                    with ss.open("rb") as f:
                        allure.attach(f.read(), name="screenshot", attachment_type=allure.attachment_type.PNG)
                    meta["attachments"].append(str(ss.resolve()))
                except Exception:
                    pass
            # page source
            ps_file = TEST_REPORT_DIR / f"page_{ts_ms}.html"
            ps = _capture_page_source(driver, ps_file)
            if ps:
                try:
                    with ps.open("rb") as f:
                        allure.attach(f.read(), name="page_source", attachment_type=allure.attachment_type.HTML)
                    meta["attachments"].append(str(ps.resolve()))
                except Exception:
                    pass

            # healing log
            heal_log = Path(HEAL_LOG)
            if heal_log.exists():
                try:
                    with heal_log.open("rb") as f:
                        allure.attach(f.read(), name="healing_log", attachment_type=allure.attachment_type.TEXT)
                    meta["attachments"].append(str(heal_log.resolve()))
                except Exception:
                    pass

            # network dump
            try:
                net_file = NETWORK_DIR / f"network_{ts_ms}.json"
                ensure_dir(NETWORK_DIR)
                dumped = driver.dump_network(net_file)
                if dumped and Path(dumped).exists():
                    try:
                        with Path(dumped).open("rb") as f:
                            allure.attach(f.read(), name="network_dump", attachment_type=allure.attachment_type.JSON)
                        meta["attachments"].append(str(Path(dumped).resolve()))
                    except Exception:
                        pass
            except Exception:
                pass

        # browser console logs
        if driver is not None and hasattr(driver, "get_log"):
            try:
                logs = driver.get_log("browser")
                if logs:
                    allure.attach(json.dumps(logs, indent=2), name="browser_console", attachment_type=allure.attachment_type.JSON)
            except Exception:
                pass

    # Always attach test metadata fixture for traceability
    try:
        if meta:
            allure.attach(json.dumps(meta, indent=2), name="test_metadata", attachment_type=allure.attachment_type.JSON)
    except Exception:
        pass

def pytest_configure(config):
    config.addinivalue_line("markers", "slow: mark test as slow")
    config.addinivalue_line("markers", "smoke: mark test as smoke")
    # ensure run root exists
    ensure_dir(TEST_REPORT_DIR)
