# SageTest — End-to-End Design Document

> **Project short name:** SageTest

---

## 1. Executive Summary
SageTest is a self-healing test automation framework built with Python, PyTest, and Selenium.  
I designed this project to reduce flaky tests, improve maintainability, and demonstrate enterprise-level CI/CD readiness.  


## 2. Goals & Success Criteria
- Achieve at least 90% reduction in locator-related failures with self-healing locators.  
- Provide a one-click automation workflow that runs locally, in Docker, and in CI.  
- Deliver CI/CD pipelines that automatically generate Allure reports and upload test artifacts to S3.  
- Ensure smoke suite completes in < 3 minutes using Docker parallelization.  


## 3. High-Level Architecture
Developer laptop / CI (GitHub Actions)
|
|-- PyTest (fixtures, plugins)
|-- Selenium driver → browsers
|
Self-Healing Module
|-- Locator store
|-- Fallback heuristics

Reports → Allure
Artifacts → S3 (reports, logs, videos)


---

## 4. Technology Stack
- Python 3.11+  
- PyTest + Selenium WebDriver  
- pytest-xdist for parallel execution  
- Allure for reporting  
- GitHub Actions for CI/CD  
- AWS S3 for artifact storage  
- Docker for reproducibility  
- WSL2 for Windows developer setup  

---

## 5. Design Details

### 5.1 AUT vs Core Separation
**AUT (Application Under Test)**  
Contains test logic and product-specific code:  
- `aut/tests/` → test cases  
- `aut/pages/` → Page Objects  
- `aut/base/` → `BasePage`, `BaseTest`  
- `aut/utils/` → helpers  
- `aut/config/` → environment configs  
- `aut/testdata/` → datasets  
- `aut/runner.py` → one-click runner  

**Core (Framework)**  
Contains reusable framework logic:  
- `core/driver_factory.py` → driver management  
- `core/locator.py` → locator abstraction  
- `core/self_heal.py` → self-healing module  
- `core/reporter.py` → Allure integration  
- `core/logger.py` → centralized logging  
- `core/metrics.py` → flakiness tracking  
- `core/docker/` → Dockerfile + docker-compose  
- `core/ci/` → GitHub Actions workflows  

---

### 5.2 Example POM Class
```python
# aut/pages/login_page.py
from core.locator import Locator

class LoginPage:
    URL = "/login"
    USER = Locator("css", "#username")
    PASS = Locator("css", "#password")
    SUBMIT = Locator("css", "button[type=submit]")

    def __init__(self, driver):
        self.driver = driver

    def open(self, base_url):
        self.driver.get(base_url + self.URL)
        return self

    def login(self, username, pwd):
        self.driver.find_element(*self.USER.by()).send_keys(username)
        self.driver.find_element(*self.PASS.by()).send_keys(pwd)
        self.driver.find_element(*self.SUBMIT.by()).click()
        return HomePage(self.driver)

6. Repo Structure
SageTest/
├─ aut/
│  ├─ base/
│  ├─ config/
│  ├─ pages/
│  ├─ test_classes/
│  ├─ tests/
│  ├─ testdata/
│  ├─ utils/
│  └─ runner.py
│
├─ core/
│  ├─ locator.py
│  ├─ self_heal.py
│  ├─ driver_factory.py
│  ├─ reporter.py
│  ├─ logger.py
│  ├─ metrics.py
│  ├─ config_loader.py
│  ├─ docker/
│  └─ ci/
│
├─ docs/
│  └─ design_document.md
├─ requirements.txt
├─ conftest.py
└─ README.md

7. One-Click Automation & WSL Setup
7.1 One-Click Automation

python aut/runner.py --mode local --suite smoke → local run

python aut/runner.py --mode docker --suite regression → Docker run

python aut/runner.py --mode ci --suite regression --upload --s3-bucket sagetest-reports → CI run

Includes:

Preflight checks

Build/run Docker

Run tests

Generate Allure report

Upload artifacts to S3

7.2 Windows + WSL Setup

Install WSL 2 (Ubuntu 22.04 recommended).

Enable Docker Desktop with WSL2 backend.

Clone repo inside WSL (~/sagetest, not /mnt/c).

Use VS Code Remote - WSL for editing.

Run tests inside WSL shell.

Access reports via \\wsl$\\Ubuntu-22.04\\home\\<user>\\sagetest\\artifacts\\<ts>\\allure-report\\index.html.

8. Benefits of AUT/Core Separation

Clear separation of test code vs framework code.

Easier to maintain and scale test suites.

Core framework reusable across multiple projects.

EOF.
