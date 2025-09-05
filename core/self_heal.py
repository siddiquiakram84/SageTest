# core/healer.py
from rapidfuzz import fuzz
from bs4 import BeautifulSoup
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
import json, time, os

HEAL_LOG = "healing_log.json"

def _log_heal(original, healed, score):
    entry = {"time": time.time(), "original": original, "healed": healed, "score": score}
    try:
        with open(HEAL_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

def _element_signature(elem):
    # Build a compact signature we can compare
    sig = {
        "tag": elem.name,
        "text": (elem.get_text() or "").strip(),
        "id": elem.get("id") or "",
        "name": elem.get("name") or "",
        "class": " ".join(elem.get("class") or []),
        "type": elem.get("type") or "",
        "aria": elem.get("aria-label") or elem.get("role") or ""
    }
    return sig

def _score_signature(target_sig, cand_sig):
    # Weighted fuzzy score between text + attr fields
    scores = []
    # text is most important
    scores.append(0.5 * (fuzz.token_sort_ratio(target_sig["text"], cand_sig["text"]) / 100.0))
    # id/name/class/aria somewhat important
    scores.append(0.2 * (fuzz.ratio(target_sig["id"], cand_sig["id"]) / 100.0))
    scores.append(0.15 * (fuzz.ratio(target_sig["name"], cand_sig["name"]) / 100.0))
    scores.append(0.1 * (fuzz.ratio(target_sig["class"], cand_sig["class"]) / 100.0))
    scores.append(0.05 * (fuzz.ratio(target_sig["aria"], cand_sig["aria"]) / 100.0))
    return sum(scores)  # normalized 0..1-ish

def find_with_healing(driver, by, locator, min_score=0.45, persist=True):
    """
    Try to find element using (by, locator). On failure, search DOM for best candidate.
    Returns a selenium WebElement if found; raises otherwise.
    """
    try:
        # Primary attempt
        elem = driver.find_element(by, locator)
        return elem
    except (NoSuchElementException, StaleElementReferenceException):
        pass

    # Build target signature using what we can infer
    target_sig = {"tag":"", "text":"", "id":"", "name":"", "class":"", "type":"", "aria":""}
    # A best-effort populate: if locator is XPath or CSS we can try to parse the intended DOM part
    try:
        # try to fetch page source and parse
        soup = BeautifulSoup(driver.page_source, "lxml")
    except Exception:
        soup = BeautifulSoup(driver.page_source, "html.parser")

    # Try to resolve original element from locator heuristically for signature
    orig_elem = None
    try:
        # if it is xpath, we can attempt to use selenium to get attributes before failure,
        # but as find_element failed, we attempt to approximate by parsing locator token (best-effort).
        # Simpler: assume locator contained visible text or id; extract heuristics:
        if locator.startswith("//") or locator.startswith("/"):
            # try to extract text from locator e.g. //button[text()='Login']
            import re
            m = re.search(r"text\(\)\s*=\s*'([^']+)'", locator)
            if m:
                target_sig["text"] = m.group(1)
        elif locator.startswith("css=") or locator.startswith(".") or "#" in locator or locator.startswith("["):
            # not reliable — leave blank
            pass
    except Exception:
        pass

    # If we couldn't build signature from locator, best fallback: user should pass expected text/tag via a helper.
    # Now scan candidate elements that are interactive or likely: buttons, a, input, span, div etc.
    candidates = []
    tags_to_check = ["a", "button", "input", "span", "label", "div"]
    for tag in tags_to_check:
        for c in soup.find_all(tag):
            sig = _element_signature(c)
            # skip tiny/empty elements
            if len(sig["text"]) < 1 and not (sig["id"] or sig["name"] or sig["class"]):
                continue
            candidates.append((c, sig))

    # If target text empty, try to infer from locator string itself (useful when locator contains a visible name)
    if not target_sig["text"]:
        # use locator token words as proxy
        import re
        words = re.sub(r"[^\w\s]", " ", locator).split()
        target_sig["text"] = " ".join(words[:6])

    # Score candidates
    scored = []
    for c, sig in candidates:
        score = _score_signature(target_sig, sig)
        scored.append((score, c, sig))
    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        raise NoSuchElementException(f"No candidates found for locator={locator}")

    best_score, best_elem, best_sig = scored[0]
    if best_score >= min_score:
        # build a stable xpath for best_elem (simple form using attributes)
        xpath = None
        if best_sig["id"]:
            xpath = f"//*[@id='{best_sig['id']}']"
        elif best_sig["name"]:
            xpath = f"//*[@name='{best_sig['name']}']"
        else:
            # fallback: tag and partial text
            text = best_sig["text"][:60].replace("'", "\"")
            xpath = f"//{best_elem.name}[contains(normalize-space(.), \"{text}\")]"

        try:
            web_elem = driver.find_element("xpath", xpath)
            if persist:
                _log_heal({"by": by, "locator": locator}, {"xpath": xpath, "score": best_score}, best_score)
            return web_elem
        except Exception as e:
            # if final find fails, still raise original exception
            raise NoSuchElementException(f"Healer found candidate but selenium find failed: {e}")
    else:
        raise NoSuchElementException(f"No healed candidate exceeding threshold (best_score={best_score:.2f})")
