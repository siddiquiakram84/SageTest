# core/self_heal.py
"""
Self-heal module for SageTest.

Provides a conservative, rule-based element healing function:
    find_with_healing(driver, by, locator, min_score=0.45, persist=True)

Dependencies (add to requirements.txt):
    beautifulsoup4
    lxml
    rapidfuzz
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

from bs4 import BeautifulSoup
from rapidfuzz import fuzz
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

HEAL_LOG = "healing_log.json"

# Tweakable: tags we consider as candidate interactive elements
_DEFAULT_TAGS = ("a", "button", "input", "label", "span", "div")

# Field weights used by _score_signature (sum should be 1.0)
_WEIGHTS = {
    "text": 0.50,
    "id": 0.20,
    "name": 0.15,
    "class": 0.10,
    "aria": 0.05,
}


def _log_heal(original: Dict[str, Any], healed: Dict[str, Any], score: float) -> None:
    entry = {
        "time": time.time(),
        "original": original,
        "healed": healed,
        "score": float(score),
    }
    try:
        p = Path(HEAL_LOG)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # never fail the test because logging failed
        pass


def _element_signature(bs_elem) -> Dict[str, str]:
    """
    Create a compact signature for a BeautifulSoup element.
    """
    return {
        "tag": bs_elem.name or "",
        "text": (bs_elem.get_text(separator=" ", strip=True) or "")[:500],
        "id": (bs_elem.get("id") or "")[:200],
        "name": (bs_elem.get("name") or "")[:200],
        "class": " ".join(bs_elem.get("class") or [])[:300],
        "type": (bs_elem.get("type") or "")[:50],
        "aria": (bs_elem.get("aria-label") or bs_elem.get("role") or "")[:200],
    }


def _score_signature(target: Dict[str, str], candidate: Dict[str, str]) -> float:
    """
    Weighted fuzzy similarity between two signatures.
    Returns a float between 0 and ~1.
    """
    total = 0.0
    # text: token sort ratio (handles word order)
    try:
        total += _WEIGHTS["text"] * (fuzz.token_sort_ratio(target["text"], candidate["text"]) / 100.0)
        total += _WEIGHTS["id"] * (fuzz.ratio(target["id"], candidate["id"]) / 100.0)
        total += _WEIGHTS["name"] * (fuzz.ratio(target["name"], candidate["name"]) / 100.0)
        total += _WEIGHTS["class"] * (fuzz.ratio(target["class"], candidate["class"]) / 100.0)
        total += _WEIGHTS["aria"] * (fuzz.ratio(target["aria"], candidate["aria"]) / 100.0)
    except Exception:
        # on any scoring error, return very low score
        return 0.0
    return float(total)


def _build_xpath_from_signature(sig: Dict[str, str], bs_elem) -> str:
    """
    Try to build a stable-ish XPath based on id/name/text fallback.
    This is intentionally simple and conservative.
    """
    if sig.get("id"):
        return f"//*[@id='{sig['id']}']"
    if sig.get("name"):
        return f"//*[@name='{sig['name']}']"
    # fallback to tag + contains(text(), '...') but escape quotes properly
    text = sig.get("text", "").strip()
    if text:
        # take a short snippet to avoid long XPaths
        snippet = text[:120].replace("'", "\"")
        return f"//{bs_elem.name}[contains(normalize-space(.), \"{snippet}\")]"
    # ultimate fallback: tag with class (first class token)
    cls = sig.get("class", "").split()
    if cls:
        return f"//{bs_elem.name}[contains(@class, '{cls[0]}')]"
    # fallback to tag only (very brittle)
    return f"//{bs_elem.name}"


def _extract_target_signature_from_locator(locator: str) -> Dict[str, str]:
    """
    Heuristic attempt to infer target text/id from the locator string (xpath/css).
    Useful when locator embeds visible text, e.g. //button[text()='Login'] or css=button.login
    """
    sig = {"tag": "", "text": "", "id": "", "name": "", "class": "", "type": "", "aria": ""}
    try:
        l = locator.strip()
        # simple xpath text() pattern
        import re
        m = re.search(r"text\(\)\s*=\s*['\"]([^'\"]+)['\"]", l)
        if m:
            sig["text"] = m.group(1)
            return sig
        # matches like contains(text(),'Login') or contains(normalize-space(.),'Login')
        m2 = re.search(r"contains\([^,]+,\s*['\"]([^'\"]+)['\"]\)", l)
        if m2:
            sig["text"] = m2.group(1)
            return sig
        # id in css like #login or xpath @id='login'
        m3 = re.search(r"(?:#|@id\s*=\s*['\"])([A-Za-z0-9_\-:]+)", l)
        if m3:
            sig["id"] = m3.group(1)
            return sig
        # classes in css like .btn-login
        m4 = re.findall(r"\.([A-Za-z0-9_\-]+)", l)
        if m4:
            sig["class"] = " ".join(m4)
            return sig
        # try to take words from locator as fallback text
        words = re.sub(r"[^\w\s]", " ", l).split()
        if words:
            sig["text"] = " ".join(words[:6])
    except Exception:
        pass
    return sig


def find_with_healing(driver: WebDriver, by: str, locator: str, min_score: float = 0.45, persist: bool = True) -> WebElement:
    """
    Try primary driver.find_element(by, locator).
    On failure, parse page source and search for best candidate using fuzzy scoring.
    If best match >= min_score, attempt to locate via an XPath built for that candidate and return the WebElement.

    Parameters:
        driver: Selenium WebDriver
        by: strategy string (e.g., "xpath", "css selector", "id", "name", etc.) — used only for primary attempt and logging
        locator: locator string
        min_score: threshold to accept healed candidate (0..1)
        persist: whether to append heal entry to HEAL_LOG

    Raises:
        NoSuchElementException when neither original nor healed candidate found.
    """
    # Primary attempt (use direct driver find)
    try:
        # Accept selenium By strings like "xpath" or "css selector"
        # If caller passed something like By.XPATH, they should pass the string here or use driver directly.
        elem = driver.find_element(by, locator)
        return elem
    except (NoSuchElementException, StaleElementReferenceException):
        # continue to healing
        pass
    except Exception:
        # unexpected error from driver.find_element -- still attempt healing path
        pass

    # Prepare page source and parse with BeautifulSoup (prefer lxml)
    page_src = ""
    try:
        page_src = driver.page_source
    except Exception:
        page_src = ""

    if not page_src:
        raise NoSuchElementException(f"Original find failed and page source unavailable for locator={locator}")

    # Parse DOM
    try:
        soup = BeautifulSoup(page_src, "lxml")
    except Exception:
        soup = BeautifulSoup(page_src, "html.parser")

    # Build target signature heuristically from locator when possible
    target_sig = _extract_target_signature_from_locator(locator)

    # If no good hint from locator, leave target text empty - we'll fallback to locator words
    if not target_sig.get("text"):
        # as a last-ditch, use token words from locator as proxy for text
        target_sig["text"] = _extract_target_signature_from_locator(locator).get("text", "") or ""

    # Collect candidates
    candidates: List[Tuple[float, Any, Dict[str, str]]] = []
    for tag in _DEFAULT_TAGS:
        for c in soup.find_all(tag):
            sig = _element_signature(c)
            # skip elements that are empty and have no id/name/class
            if not sig["text"] and not (sig["id"] or sig["name"] or sig["class"]):
                continue
            score = _score_signature(target_sig, sig)
            candidates.append((score, c, sig))

    if not candidates:
        raise NoSuchElementException(f"No candidate elements found for locator={locator}")

    # Sort by descending score
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, best_bs_elem, best_sig = candidates[0]

    if best_score < min_score:
        # no acceptable heal found
        raise NoSuchElementException(f"No healed candidate exceeding threshold (best_score={best_score:.2f}) for locator={locator}")

    # Build an XPath for Selenium to locate the candidate
    xpath = _build_xpath_from_signature(best_sig, best_bs_elem)

    # Try to get WebElement from driver using constructed xpath
    try:
        web_elem = driver.find_element("xpath", xpath)
        if persist:
            _log_heal({"by": by, "locator": locator}, {"xpath": xpath, "signature": best_sig}, best_score)
        return web_elem
    except Exception as e:
        # If that fails, try alternative robust approaches:
        # 1) if element has id or name, try those direct finds
        try:
            if best_sig.get("id"):
                web_elem = driver.find_element("id", best_sig["id"])
                if persist:
                    _log_heal({"by": by, "locator": locator}, {"strategy": "id", "value": best_sig["id"], "signature": best_sig}, best_score)
                return web_elem
            if best_sig.get("name"):
                web_elem = driver.find_element("name", best_sig["name"])
                if persist:
                    _log_heal({"by": by, "locator": locator}, {"strategy": "name", "value": best_sig["name"], "signature": best_sig}, best_score)
                return web_elem
        except Exception:
            pass

        # If still not found, raise with context
        raise NoSuchElementException(f"Healer located candidate but driver couldn't find it by xpath/id/name. xpath={xpath} error={e}")


# Optional convenience: helper to read healing log as list
def read_heal_log(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    p = Path(HEAL_LOG)
    if not p.exists():
        return entries
    try:
        with p.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if limit is not None and i >= limit:
                    break
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return entries
