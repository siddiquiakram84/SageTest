#!/usr/bin/env python3
"""
runner.py - run selected tests from aut/config/testcase.json, validate config,
generate Allure HTML, copy standardized HTML, print-to-PDF (if chrome present),
and write run_manifest.json.

Usage:
    python runner.py [--tags TAG1,TAG2] [--env ENVNAME] [--workers N|'auto'] [--dry-run]

Notes:
 - Config path: aut/config/testcase.json
 - Requires: pytest, pytest-xdist, allure-pytest (for results), Allure CLI on PATH, Chrome (for PDF)
 - Writes:
     aut/test_report/<ts>/allure-results
     aut/suite_report/<suite>/<ts>/allure-report
     aut/report_result/<suite>__<ts>__<status>.html|.pdf
     aut/report_result/<suite>__<ts>__<status>__manifest.json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import shutil

# third-party used for config validation
try:
    from jsonschema import validate, ValidationError
except Exception:
    print("Please install jsonschema: pip install jsonschema")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "aut" / "config" / "testcase.json"

# Default artifact directories (can be overridden by config)
DEFAULT_TEST_REPORT = ROOT / "aut" / "test_report"
DEFAULT_SUITE_REPORT = ROOT / "aut" / "suite_report"
DEFAULT_RESULT_DIR = ROOT / "aut" / "report_result"

TS_FMT = "%Y%m%d_%H%M%S"

# Minimal JSON schema for validation (can be extended)
CONFIG_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "suite_name", "env", "groups"],
    "properties": {
        "schema_version": {"type": "string"},
        "suite_name": {"type": "string"},
        "env": {"type": "object"},
        "execution": {"type": "object"},
        "filters": {"type": "object"},
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "tests"],
                "properties": {
                    "name": {"type": "string"},
                    "tests": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "run"],
                            "properties": {
                                "id": {"type": "string"},
                                "run": {"type": "boolean"},
                                "tags": {"type": "array"},
                                "priority": {"type": "string"}
                            }
                        }
                    }
                }
            }
        },
        "artifacts": {"type": "object"},
        "hooks": {"type": "object"}
    }
}

def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        validate(instance=data, schema=CONFIG_SCHEMA)
    except ValidationError as e:
        raise ValueError(f"Config validation failed: {e.message}")
    return data

def build_selected_tests(cfg: Dict[str, Any], override_tags: Optional[List[str]] = None) -> List[str]:
    """
    Return list of pytest nodeids to run (exact nodeids).
    If override_tags provided, select tests that have at least one of those tags.
    """
    selected: List[str] = []
    groups = cfg.get("groups", [])
    for g in groups:
        for t in g.get("tests", []):
            run_flag = t.get("run", False)
            tags = [str(x) for x in (t.get("tags") or [])]
            if override_tags:
                # select by tag intersection
                if set(tags).intersection(set(override_tags)):
                    run_flag = True
                else:
                    run_flag = False
            if run_flag:
                selected.append(t["id"])
    # deduplicate while preserving order
    seen = set()
    dedup = []
    for s in selected:
        if s not in seen:
            dedup.append(s); seen.add(s)
    return dedup

def ensure_dirs(dirs: List[Path]):
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

def run_cmd(cmd: List[str], cwd: Optional[Path] = None, check: bool = True):
    print("> " + " ".join(cmd))
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=check)

def find_chrome_binary(provided_path: str = "") -> Optional[str]:
    if provided_path:
        p = Path(provided_path)
        if p.exists():
            return str(p)
    for name in ("google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None

def make_manifest(info: Dict[str, Any], path: Path):
    try:
        path.write_text(json.dumps(info, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Warning: failed to write manifest: {e}")

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--tags", type=str, default="", help="Comma-separated tags to run (overrides per-test run flags)")
    parser.add_argument("--env", type=str, default="", help="Override env.name from config")
    parser.add_argument("--workers", type=str, default="", help="'auto' or integer to override execution.workers")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and show tests that would run, but do not execute")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(CONFIG_PATH)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)
    except ValueError as e:
        print(e)
        sys.exit(2)

    # apply simple CLI overrides
    if args.env:
        cfg.setdefault("env", {})["name"] = args.env
    if args.workers:
        cfg.setdefault("execution", {})["workers"] = args.workers

    override_tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None

    suite_name = cfg.get("suite_name", "suite")
    ts = datetime.now().strftime(TS_FMT)

    # directories from config or defaults
    artifacts = cfg.get("artifacts", {})
    test_report_root = (ROOT / artifacts.get("test_report_dir")) if artifacts.get("test_report_dir") else DEFAULT_TEST_REPORT
    suite_report_root = (ROOT / artifacts.get("suite_report_dir")) if artifacts.get("suite_report_dir") else DEFAULT_SUITE_REPORT
    result_dir = (ROOT / artifacts.get("result_dir")) if artifacts.get("result_dir") else DEFAULT_RESULT_DIR

    # create timestamped locations
    allure_results_dir = test_report_root / ts / "allure-results"
    suite_report_ts_dir = suite_report_root / suite_name / ts
    ensure_dirs([allure_results_dir, suite_report_ts_dir, result_dir])

    # which tests to run (exact nodeids)
    tests_to_run = build_selected_tests(cfg, override_tags=override_tags)
    print(f"Selected {len(tests_to_run)} tests from config (first 10): {tests_to_run[:10]}")

    manifest: Dict[str, Any] = {
        "suite_name": suite_name,
        "timestamp": ts,
        "env": cfg.get("env", {}),
        "tests_selected": tests_to_run,
        "override_tags": override_tags,
        "status": "not_started"
    }

    # dry-run: show manifest and exit
    if args.dry_run:
        print("Dry-run mode: manifest below")
        print(json.dumps(manifest, indent=2))
        manifest["status"] = "dry_run"
        manifest_path = result_dir / f"{suite_name}__{ts}__manifest.json"
        make_manifest(manifest, manifest_path)
        print(f"Manifest written to {manifest_path}")
        return

    # Build pytest invocation
    pytest_cmd = [sys.executable, "-m", "pytest"]
    # workers
    workers_cfg = cfg.get("execution", {}).get("workers", "auto")
    if args.workers:
        workers_cfg = args.workers
    if cfg.get("execution", {}).get("parallel", False) or workers_cfg:
        # require pytest-xdist: -n auto or -n <N>
        if workers_cfg == "auto" or workers_cfg == "" or workers_cfg is None:
            pytest_cmd += ["-n", "auto"]
        else:
            pytest_cmd += ["-n", str(workers_cfg)]
    # add nodeids if any, else run all
    if tests_to_run:
        pytest_cmd += tests_to_run
    # set allure directory
    pytest_cmd += ["--alluredir", str(allure_results_dir)]

    # run pytest
    status = "passed"
    try:
        print("Running pytest...")
        run_cmd(pytest_cmd, cwd=ROOT)
    except subprocess.CalledProcessError as e:
        print("pytest exit with non-zero (some tests failed). See pytest output.")
        status = "failed"
    except Exception as e:
        print(f"Error running pytest: {e}")
        status = "error"

    manifest["status"] = status
    manifest["allure_results_dir"] = str(allure_results_dir)
    manifest_path = result_dir / f"{suite_name}__{ts}__manifest.json"
    make_manifest(manifest, manifest_path)

    # generate Allure HTML site
    try:
        run_cmd(["allure", "generate", str(allure_results_dir), "--clean", "-o", str(suite_report_ts_dir)], cwd=ROOT)
        print(f"Allure HTML generated at: {suite_report_ts_dir}")
    except Exception as e:
        print("Failed to generate Allure report. Ensure Allure CLI is installed and on PATH.")
        print(e)
        sys.exit(3)

    # copy standardized HTML to result dir
    index_html = suite_report_ts_dir / "index.html"
    safe_suite = suite_name.replace(" ", "_")
    base_name = f"{safe_suite}__{ts}__{status}"
    html_dest = result_dir / f"{base_name}.html"
    pdf_dest = result_dir / f"{base_name}.pdf"

    if index_html.exists():
        shutil.copy(index_html, html_dest)
        print(f"Copied report HTML to: {html_dest}")
    else:
        print("Warning: generated index.html not found; skipping copy.")

    # Convert HTML -> PDF using Chrome if available
    chrome_bin = find_chrome_binary(cfg.get("env", {}).get("chrome_path", "") or "")
    if not chrome_bin:
        print("Chrome/Chromium binary not found in PATH. Skipping PDF generation.")
    else:
        url = f"file://{html_dest.resolve()}"
        chrome_cmd = [
            chrome_bin,
            "--headless",
            "--disable-gpu",
            f"--print-to-pdf={str(pdf_dest.resolve())}",
            url
        ]
        # Add sandbox flags if running in container/CI
        if os.getenv("CI") == "true" or os.getenv("DOCKER") == "true":
            chrome_cmd.insert(1, "--no-sandbox")
            chrome_cmd.insert(2, "--disable-dev-shm-usage")
        try:
            run_cmd(chrome_cmd, cwd=result_dir)
            if pdf_dest.exists():
                print(f"PDF created at: {pdf_dest}")
            else:
                print("Chrome returned successfully but PDF not found. Check Chrome flags.")
        except Exception as e:
            print("Failed to generate PDF using Chrome:", e)

    # Finalize manifest with generated artifacts
    manifest["generated"] = {
        "suite_report_dir": str(suite_report_ts_dir),
        "html": str(html_dest) if html_dest.exists() else None,
        "pdf": str(pdf_dest) if pdf_dest.exists() else None
    }
    make_manifest(manifest, manifest_path)
    print("Run manifest:", manifest_path)
    print("Done.")

if __name__ == "__main__":
    main()
