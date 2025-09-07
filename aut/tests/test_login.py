import pytest
from aut.pages.login_page import LoginPage

@pytest.mark.smoke
def test_login_happy_path(driver, base_url):
    login = LoginPage(driver, base_url=base_url)
    login.load()
    login.login("standard_user", "secret_sauce")
    assert "inventory" in driver.current_url
