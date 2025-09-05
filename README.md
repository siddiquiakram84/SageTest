# SageTest — Intelligent Test Automation with Python & PyTest

## Overview
**SageTest** is an intelligent, self-healing automation framework built with **Python & PyTest**.  
It minimizes flaky tests and provides **enterprise-grade CI/CD pipelines** with Allure reporting, Dockerized execution, and AWS S3 artifact storage.

### Features
- 🔹 **Self-Healing Locators** — fallback strategies reduce flaky failures.  
- 🔹 **PyTest + Selenium** — modular, scalable test automation stack.  
- 🔹 **Allure Reporting** — rich reports with screenshots/logs.  
- 🔹 **One-Click Automation** — run everything (local/CI/Docker) in a single command.  
- 🔹 **Reusable Core** — framework separated from AUT logic.  
- 🔹 **WSL2 Friendly** — designed for Windows developers using WSL.  

---

## Quickstart

### Local Run
```bash
git clone https://github.com/your-username/sagetest.git
cd sagetest
pip install -r requirements.txt
pytest aut/tests/smoke -k login --alluredir=allure-results

One-Click Runner
python aut/runner.py --mode docker --suite smoke

CI/CD

Uses GitHub Actions (core/ci/ci.yml).

Publishes Allure results + artifacts to S3.

Project Structure
SageTest/
├─ aut/                      # AUT-specific automation
│  ├─ base/                  # BasePage, BaseTest
│  ├─ config/                # env configs (local.yaml, staging.yaml)
│  ├─ pages/                 # Page Objects
│  ├─ test_classes/          # Test class orchestrators
│  ├─ tests/                 # smoke/ regression suites
│  ├─ testdata/              # datasets
│  ├─ utils/                 # utilities (data generators, waits)
│  └─ runner.py              # one-click Python runner
│
├─ core/                     # Framework-level
│  ├─ locator.py
│  ├─ self_heal.py
│  ├─ driver_factory.py
│  ├─ reporter.py
│  ├─ logger.py
│  ├─ metrics.py
│  ├─ config_loader.py
│  ├─ docker/                # Dockerfile + docker-compose
│  └─ ci/                    # CI workflows
│
├─ docs/                     # Documentation
│  └─ design_document.md
├─ requirements.txt
├─ conftest.py
└─ README.md

Documentation

Full design details: docs/design_document.md
