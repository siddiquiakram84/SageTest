import pytest
from aut.pages.login_page import LoginPage

@pytest.mark.smoke
class TestLoginSuite:
    def test_valid_login(self, driver, base_url):
        login = LoginPage(driver, base_url=base_url)
        login.load()
        login.login("standard_user", "secret_sauce")
        assert "inventory" in driver.current_url

    def test_invalid_login(self, driver, base_url):
        login = LoginPage(driver, base_url=base_url)
        login.load()
        login.login("locked_out_user", "secret_sauce")
        assert "error" in driver.page_source.lower()
