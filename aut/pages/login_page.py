from selenium.webdriver.common.by import By

class LoginPage:
    def __init__(self, driver, base_url: str):
        self.driver = driver
        self.base_url = base_url
        self.username_input = (By.ID, "user-name")
        self.password_input = (By.ID, "password")
        self.login_button = (By.ID, "login-button")

    def load(self):
        self.driver.get(self.base_url)

    def login(self, username: str, password: str):
        self.driver.find_element(*self.username_input).send_keys(username)
        self.driver.find_element(*self.password_input).send_keys(password)
        self.driver.find_element(*self.login_button).click()
