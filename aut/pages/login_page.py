# aut/pages/login_page.py
from selenium.webdriver.common.by import By
from aut.base.base_page import BasePage

class LoginPage(BasePage):
    USER = (By.ID, "user-name")
    PASS = (By.ID, "password")
    BTN = (By.ID, "login-button")

    def load(self):
        self.goto("/")

    def login(self, username: str, password: str):
        self.type(*self.USER, text=username)
        self.type(*self.PASS, text=password)
        self.click(*self.BTN)
