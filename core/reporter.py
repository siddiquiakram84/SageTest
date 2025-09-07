# core/reporter.py
"""
Reporter utilities: generate full Allure site, create single-file dashboard,
create standalone HTML snapshot and PDF.

Implements:
    generate_dashboard_and_pdf(test_report_dir: Path, suite_report_ts_dir: Path,
                               result_dir: Path, suite_name: str, ts: str, status: str,
                               metadata: dict) -> dict
Return dict keys: allure_site, suite_index, standalone_html, pdf
"""
from __future__ import annotations
import json
import shutil
import subprocess
import time
import socket
from pathlib import Path
from typing import Dict, Any, Optional

# try to use core.logger if present
try:
    from core.logger import get_logger
    _logger = get_logger  # function
except Exception:
    _logger = None

def _log(msg: str):
    if _logger:
        # create a temporary logger placed under aut/logs if possible
        try:
            lg = get_logger(Path("aut/logs"), time.strftime("%Y%m%d_%H%M%S"))
            lg.info(msg)
            return
        except Exception:
            pass
    print(msg)

def _find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def generate_dashboard_and_pdf(test_report_dir: Path, suite_report_ts_dir: Path,
                               result_dir: Path, suite_name: str, ts: str, status: str,
                               metadata: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    Generate the full Allure site under test_report_dir/allure_site,
    create a single-file dashboard under suite_report_ts_dir/index.html,
    write a standalone HTML into result_dir and attempt to create a PDF.
    Returns a dict with keys: allure_site, suite_index, standalone_html, pdf
    """
    test_report_dir = Path(test_report_dir)
    suite_report_ts_dir = Path(suite_report_ts_dir)
    result_dir = Path(result_dir)
    ensure_dirs = lambda p: p.mkdir(parents=True, exist_ok=True)

    ensure_dirs([test_report_dir, suite_report_ts_dir, result_dir])

    tmp_out = test_report_dir / "allure_site_tmp"
    final_site = test_report_dir / "allure_site"
    # generate Allure static site
    try:
        if tmp_out.exists():
            shutil.rmtree(tmp_out)
        subprocess.run(["allure", "generate", str(test_report_dir), "--clean", "-o", str(tmp_out)],
                       check=True)
        if final_site.exists():
            shutil.rmtree(final_site)
        shutil.copytree(tmp_out, final_site)
        if tmp_out.exists():
            shutil.rmtree(tmp_out)
        _log(f"Allure static site generated at {final_site}")
    except Exception as e:
        _log(f"Allure generate failed: {e}")
        final_site = final_site if final_site.exists() else None

    # Build dashboard HTML
    safe_suite = suite_name.replace(" ", "_")
    base_name = f"{safe_suite}__{ts}__{status}"
    standalone_html = result_dir / f"{base_name}.html"
    pdf_path = result_dir / f"{base_name}.pdf"
    dashboard = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>{suite_name} - Dashboard</title></head>
<body>
  <h1>{suite_name} — {ts}</h1>
  <p>Status: <strong>{status}</strong></p>
  <pre>{json.dumps(metadata, indent=2)}</pre>
  <p>Full Allure site: <a href="file://{final_site / 'index.html'}">open local Allure</a></p>
</body>
</html>
"""
    suite_index = suite_report_ts_dir / "index.html"
    ensure_dirs([suite_report_ts_dir])
    suite_index.write_text(dashboard, encoding="utf-8")
    standalone_html.write_text(dashboard, encoding="utf-8")

    # Try PDF generation: serve final_site over HTTP and point headless Chrome
    chrome_bin = None
    import shutil as _shutil
    for name in ("google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"):
        path = _shutil.which(name)
        if path:
            chrome_bin = path
            break

    if chrome_bin and final_site and final_site.exists():
        port = _find_free_port()
        http_cmd = [sys.executable, "-m", "http.server", str(port), "--directory", str(final_site)]
        proc = subprocess.Popen(http_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.4)
        url = f"http://127.0.0.1:{port}/index.html"
        chrome_cmd = [chrome_bin, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
                      f"--print-to-pdf={str(pdf_path.resolve())}", url]
        try:
            subprocess.run(chrome_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            chrome_cmd[1] = "--headless"
            subprocess.run(chrome_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            try:
                proc.terminate()
            except Exception:
                pass
        if pdf_path.exists():
            _log(f"PDF generated at {pdf_path}")
        else:
            _log("PDF generation finished but file not found")
    else:
        _log("Chrome not found or full Allure site missing; skipping PDF generation")

    return {
        "allure_site": str(final_site.resolve()) if final_site and final_site.exists() else None,
        "suite_index": str(suite_index.resolve()),
        "standalone_html": str(standalone_html.resolve()),
        "pdf": str(pdf_path.resolve()) if pdf_path.exists() else None
    }
