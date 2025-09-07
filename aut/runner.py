#!/usr/bin/env python3
"""
Updated runner.py (place at SageTest1/aut/runner.py)

- Writes artifacts under aut/test_report/<TS> (single run folder)
- Writes single dashboard HTML at aut/suite_report/<suite>/<TS>/index.html
- Writes standalone HTML + PDF at aut/report_result/<suite>__<TS>__<status>.(html|pdf)
- Serves dashboard HTML locally and uses headless Chrome to create PDF (prevents blank PDFs)
- Keeps console output minimal
- Redirects Python/pytest caches outside project
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Prefer core modules when present
try:
    from core import reporter as core_reporter
except Exception:
    core_reporter = None

try:
    from core import config_loader
except Exception:
    config_loader = None

# constants / paths
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent.parent  # SageTest1
AUT_ROOT = PROJECT_ROOT / "aut"
CONFIG_PATH = AUT_ROOT / "config" / "testcase.json"
METADATA_FILE = AUT_ROOT / "report_metadata.json"

TEST_REPORT_ROOT = AUT_ROOT / "test_report"
SUITE_REPORT_ROOT = AUT_ROOT / "suite_report"
RESULT_DIR = AUT_ROOT / "report_result"
LOG_DIR = AUT_ROOT / "logs"

TS_FMT = "%Y%m%d_%H%M%S"

# local fallback config loader (if core.config_loader not present)
def _local_load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config: {path}")
    return json.loads(path.read_text(encoding="utf-8"))

# helpers
def _quiet_print(*a, **kw):
    print(*a, **kw)

def _find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def _ensure_dirs(paths: List[Path]):
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)

def _get_chrome_bin(provided: str = "") -> Optional[str]:
    if provided:
        p = Path(provided)
        if p.exists():
            return str(p)
    import shutil
    for name in ("google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None

def _serve_and_print_to_pdf(html_path: Path, pdf_out: Path, chrome_bin: str) -> bool:
    """
    Serve the directory containing html_path on a free port and instruct chrome to print it to pdf.
    Returns True if pdf_out exists after operation.
    """
    serve_dir = html_path.parent
    port = _find_free_port()
    cmd = [sys.executable, "-m", "http.server", str(port), "--directory", str(serve_dir)]
    http_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=PROJECT_ROOT)
    time.sleep(0.4)
    url = f"http://127.0.0.1:{port}/{html_path.name}"
    chrome_cmd = [
        chrome_bin,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        f"--print-to-pdf={str(pdf_out.resolve())}",
        url
    ]
    try:
        subprocess.run(chrome_cmd, cwd=PROJECT_ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        # fallback classic headless
        chrome_cmd[1] = "--headless"
        subprocess.run(chrome_cmd, cwd=PROJECT_ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        try:
            http_proc.terminate()
        except Exception:
            pass
    return pdf_out.exists()

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--tags", type=str, default="", help="Comma-separated tags to run")
    parser.add_argument("--env", type=str, default="", help="Override env.name from config")
    parser.add_argument("--workers", type=str, default="", help="'auto' or integer to override execution.workers")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and show tests that would run")
    parser.add_argument("--keep-cache", action="store_true", help="Keep caches in temp for debugging")
    args = parser.parse_args(argv)

    # load config
    try:
        cfg = (config_loader.load_config(CONFIG_PATH) if config_loader and hasattr(config_loader, "load_config")
               else _local_load_config(CONFIG_PATH))
    except Exception as e:
        _quiet_print("Config error:", e)
        sys.exit(1)

    if args.env:
        cfg.setdefault("env", {})["name"] = args.env
    if args.workers:
        cfg.setdefault("execution", {})["workers"] = args.workers

    override_tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    suite_name = cfg.get("suite_name", "suite")
    ts = datetime.now().strftime(TS_FMT)
    os.environ["SAGETEST_TS"] = ts

    # redirect caches out of project
    tmp_root = Path(tempfile.gettempdir()) / "sagetest_cache" / ts
    pycache_prefix = tmp_root / "pycache_prefix"
    pytest_cache_dir = tmp_root / "pytest_cache"
    _ensure_dirs([pycache_prefix, pytest_cache_dir])
    os.environ["PYTHONPYCACHEPREFIX"] = str(pycache_prefix.resolve())
    os.environ["SAGETEST_CACHE_ROOT"] = str(tmp_root.resolve())

    # artifact layout
    test_report_dir = TEST_REPORT_ROOT / ts            # single directory for run (contains raw results, network, screenshots, allure_site/)
    suite_report_ts_dir = SUITE_REPORT_ROOT / suite_name / ts
    result_dir = RESULT_DIR
    log_dir = LOG_DIR
    _ensure_dirs([test_report_dir, suite_report_ts_dir, result_dir, log_dir])

    # Which tests to run: select from cfg -> build node ids
    tests_to_run = []
    for g in cfg.get("groups", []):
        for t in g.get("tests", []):
            run_flag = t.get("run", False)
            tags = [str(x) for x in (t.get("tags") or [])]
            if override_tags:
                run_flag = bool(set(tags).intersection(set(override_tags)))
            if run_flag:
                tests_to_run.append(t["id"])
    # deduplicate
    seen = set(); dedup = []
    for s in tests_to_run:
        if s not in seen:
            dedup.append(s); seen.add(s)
    tests_to_run = dedup
    _quiet_print(f"Selected {len(tests_to_run)} tests")

    manifest: Dict[str, Any] = {
        "suite_name": suite_name,
        "timestamp": ts,
        "env": cfg.get("env", {}),
        "tests_selected": tests_to_run,
        "override_tags": override_tags,
        "status": "not_started"
    }

    if args.dry_run:
        manifest["status"] = "dry_run"
        manifest_path = result_dir / f"{suite_name}__{ts}__manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        _quiet_print("Dry-run manifest:", manifest_path)
        return

    # Build pytest command quietly and redirect cache
    pytest_cmd = [sys.executable, "-m", "pytest", "-q", "--disable-warnings"]
    workers_cfg = cfg.get("execution", {}).get("workers", "auto")
    if args.workers:
        workers_cfg = args.workers
    if cfg.get("execution", {}).get("parallel", False) or workers_cfg:
        if workers_cfg == "auto" or workers_cfg in ("", None):
            pytest_cmd += ["-n", "auto"]
        else:
            pytest_cmd += ["-n", str(workers_cfg)]
    if tests_to_run:
        pytest_cmd += tests_to_run
    pytest_cmd += ["--alluredir", str(test_report_dir), "--cache-dir", str(pytest_cache_dir)]

    # Run pytest
    status = "passed"
    # Build base pytest command list (we already added -q and workers etc.)
    # pytest_cmd variable should already be assembled above and include "--alluredir", etc.
    # We'll attempt one dry run with capture to check if pytest accepts --cache-dir.
    try:
        # First attempt: run pytest capturing output to detect argument errors
        proc = subprocess.run(pytest_cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode == 0:
            # Tests passed (quiet run)
            # Optionally print a short summary line, keep logs minimal
            _quiet_print(f"pytest finished: returncode=0")
        else:
            # Non-zero: check stderr for unrecognized-argument style message
            err_text = (proc.stderr or "").lower()
            if "unrecognized arguments" in err_text and "--cache-dir" in err_text:
                _quiet_print("pytest reported it does not accept --cache-dir; retrying without it...")
                # Remove cache-dir option if present in list
                pytest_cmd_no_cache = [p for p in pytest_cmd if p != "--cache-dir" and not (p.startswith(str(pytest_cache_dir)))]
                # Ensure we also strip the cache-dir value if it was provided as separate token
                # If original was ["--cache-dir", "/path"], the comprehension above left the value token; remove any token equal to the path
                pytest_cmd_no_cache = [p for p in pytest_cmd_no_cache if p != str(pytest_cache_dir)]
                # Now run pytest again but stream output to console so user sees it
                subprocess.run(pytest_cmd_no_cache, cwd=PROJECT_ROOT, check=False)
                # We don't have the returncode here; assume status from return code is reflected by subsequent lines
                # Optionally set status to 'failed' if the second run returned non-zero (we could capture it similarly)
                # For simplicity, leave status determination to manifest stage below (if needed you can capture return code)
                status = "failed" if proc.returncode != 0 else "passed"
            else:
                # Some other pytest error — print a helpful excerpt and mark failed
                _quiet_print("pytest failed. Stderr (trimmed):")
                for line in (proc.stderr or "").splitlines()[-20:]:
                    _quiet_print(line)
                status = "failed"
    except Exception as e:
        _quiet_print("Error invoking pytest:", e)
        status = "error"

    manifest["status"] = status
    manifest["allure_results_dir"] = str(test_report_dir.resolve())
    manifest_path = result_dir / f"{suite_name}__{ts}__manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Read metadata file (use it and also copy into run dir so conftest+reporter have exact copy)
    metadata = {}
    if METADATA_FILE.exists():
        try:
            metadata = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}
    # attach run-level metadata + status
    metadata_run = dict(metadata)
    metadata_run.update({"suite": suite_name, "timestamp": ts, "status": status})
    # write a copy inside test_report_dir for traceability
    run_meta_path = test_report_dir / "run_metadata.json"
    run_meta_path.write_text(json.dumps(metadata_run, indent=2), encoding="utf-8")

    # Generate Allure full static site & dashboard:
    generated: Dict[str, Optional[str]] = {}
    if core_reporter and hasattr(core_reporter, "generate_dashboard_and_pdf"):
        try:
            generated = core_reporter.generate_dashboard_and_pdf(
                test_report_dir=test_report_dir,
                suite_report_ts_dir=suite_report_ts_dir,
                result_dir=result_dir,
                suite_name=suite_name,
                ts=ts,
                status=status,
                metadata=metadata_run
            )
        except Exception as e:
            _quiet_print("core.reporter failed, falling back to local generation:", e)
            generated = {}
    if not generated:
        # Local fallback: produce dashboard HTML (detailed) and keep full site (if Allure CLI available)
        # generate Allure static site into test_report_dir/allure_site
        tmp_site = test_report_dir / "allure_site_tmp"
        final_site = test_report_dir / "allure_site"
        try:
            if tmp_site.exists():
                shutil.rmtree(tmp_site)
            subprocess.run(["allure", "generate", str(test_report_dir), "--clean", "-o", str(tmp_site)],
                           cwd=PROJECT_ROOT, check=True)
            if final_site.exists():
                shutil.rmtree(final_site)
            shutil.copytree(tmp_site, final_site)
            if tmp_site.exists():
                shutil.rmtree(tmp_site)
        except Exception:
            final_site = final_site if final_site.exists() else None

        # Build a detailed dashboard HTML (detailed info + links to full allure site and artifacts)
        safe_suite = suite_name.replace(" ", "_")
        base_name = f"{safe_suite}__{ts}__{status}"
        standalone_html = result_dir / f"{base_name}.html"
        pdf_out = result_dir / f"{base_name}.pdf"
        # Compose a rich HTML that contains metadata, links, and a short test summary placeholder
        dashboard_html = f"""
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{suite_name} — Run {ts}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  body{{font-family:Arial,Helvetica,sans-serif;margin:22px;color:#222}}
  .wrap{{max-width:980px;margin:auto}}
  .header{{display:flex;justify-content:space-between;align-items:center}}
  .card{{border:1px solid #e6e6e6;padding:16px;border-radius:8px;margin-top:12px;background:#fff}}
  h1{{margin:0;font-size:20px}}
  pre{{background:#f6f8fa;padding:12px;border-radius:6px;overflow:auto}}
  .actions a{{display:inline-block;margin-right:8px;padding:8px 12px;background:#0366d6;color:#fff;text-decoration:none;border-radius:6px}}
</style>
</head>
<body>
  <div class="wrap">
    <div class="header"><h1>{suite_name} — Run {ts}</h1><div><small>Status: <strong>{status}</strong></small></div></div>

    <div class="card">
      <h3>Run Metadata</h3>
      <pre>{json.dumps(metadata_run, indent=2)}</pre>
    </div>

    <div class="card">
      <h3>Artifacts</h3>
      <ul>
        <li>Raw run folder: <code>{test_report_dir.resolve()}</code></li>
        <li>Full Allure site (interactive): <code>{(final_site.resolve() if final_site else 'NOT_GENERATED')}</code></li>
      </ul>
      <div class="actions">
        <a href="file://{(final_site.resolve() / 'index.html') if final_site else ''}">Open Full Allure Site</a>
        <a href="file://{standalone_html.resolve()}">Open This Report (HTML)</a>
      </div>
    </div>

    <div class="card">
      <h3>Notes</h3>
      <p>Use the interactive Allure site for drill-down. This PDF contains a snapshot with metadata and links.</p>
    </div>
  </div>
</body>
</html>
"""
        suite_index = suite_report_ts_dir / "index.html"
        suite_index.write_text(dashboard_html, encoding="utf-8")
        standalone_html.write_text(dashboard_html, encoding="utf-8")
        generated = {
            "allure_site": str(final_site.resolve()) if final_site else None,
            "suite_index": str(suite_index.resolve()),
            "standalone_html": str(standalone_html.resolve()),
            "pdf": None
        }
        # generate PDF from the standalone_html (detailed document)
        chrome_bin = _get_chrome_bin(cfg.get("env", {}).get("chrome_path", "") or "")
        if chrome_bin:
            ok = _serve_and_print_to_pdf(standalone_html, pdf_out, chrome_bin)
            if ok:
                generated["pdf"] = str(pdf_out.resolve())

    # Ensure result_dir contains only HTML + PDF for this run (we only create these two files per run)
    # (Other artifacts remain in test_report_dir)
    manifest["generated"] = generated
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Print final concise paths (absolute)
    _quiet_print("\n=== REPORT PATHS ===")
    _quiet_print("Suite dashboard (single file):", generated.get("suite_index"))
    _quiet_print("Standalone HTML:", generated.get("standalone_html"))
    _quiet_print("Standalone PDF:", generated.get("pdf"))
    _quiet_print("Raw run folder (artifacts & network logs):", str(test_report_dir.resolve()))
    _quiet_print("====================\n")

    # cleanup caches unless requested
    if not args.keep_cache:
        try:
            shutil.rmtree(tmp_root)
        except Exception:
            pass

if __name__ == "__main__":
    main()



# # (optional) ensure TS is exported for manual runs; runner will export automatically when it invokes pytest
# export SAGETEST_TS=$(date +%Y%m%d_%H%M%S)

# # run runner (runner lives at aut/runner.py)
# python aut/runner.py --workers auto
# # or dry run:
# python aut/runner.py --dry-run
