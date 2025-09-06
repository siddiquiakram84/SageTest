# aut/base/base_page.py
from selenium.webdriver.remote.webdriver import WebDriver
from typing import Optional, Tuple

class BasePage:
    def __init__(self, driver: WebDriver, base_url: Optional[str] = None):
        self.driver = driver
        self.base_url = base_url.rstrip("/") if base_url else None

    def goto(self, path: str = "/"):
        url = (self.base_url + path) if self.base_url else path
        self.driver.get(url)

    def find(self, by: str, locator: str, heal: bool = True, **kwargs):
        # uses monkey-patched driver.find_with_heal if available
        if hasattr(self.driver, "find_with_heal"):
            return self.driver.find_with_heal(by, locator, heal=heal, **kwargs)
        return self.driver.find_element(by, locator)

    def click(self, by: str, locator: str, heal: bool = True):
        el = self.find(by, locator, heal=heal)
        el.click()

    def type(self, by: str, locator: str, text: str, heal: bool = True):
        el = self.find(by, locator, heal=heal)
        el.clear()
        el.send_keys(text)
