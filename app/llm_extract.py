"""Optional: ask a local LLM to pick owner/founder names out of website text.

Off unless LLM_BASE_URL and LLM_MODEL are set (in .env). Works with any server
that speaks the OpenAI chat-completions format: Ollama, LM Studio, llama.cpp,
vLLM. Emails and phone numbers never need it; the regex extraction handles
those. Every name the model returns must appear verbatim in the page text, so
it cannot invent people.

    LLM_BASE_URL   e.g. http://localhost:11434/v1  (Ollama) or http://localhost:1234/v1 (LM Studio)
    LLM_MODEL      e.g. llama3.1:8b
    LLM_API_KEY    only if your server requires one
"""
import json
import os
import re
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.webdata_client import load_env_file

MAX_TEXT_CHARS = 8000
TIMEOUT_SECONDS = 120
PROMPT = (
    "From the company website text below, list the people who are explicitly named "
    "as founder, co-founder, owner, CEO, managing director, president or managing partner. "
    "Use only names and titles written in the text; never guess. "
    'Answer with JSON only: [{"name": "...", "title": "..."}], or [] if nobody is named.\n\n'
    "TEXT:\n"
)


def is_configured():
    load_env_file()
    return bool(os.environ.get("LLM_BASE_URL", "").strip() and os.environ.get("LLM_MODEL", "").strip())


def parse_people(reply, page_text):
    """Turn the model's reply into "Name (Title)" entries found in page_text."""
    match = re.search(r"\[.*\]", reply, re.S)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    people = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        title = str(item.get("title") or "").strip()
        if name and title and name in page_text:
            entry = f"{name} ({title[:60]})"
            if entry not in people:
                people.append(entry)
    return people[:5]


def find_decision_makers(page_text):
    """Return "Name (Title)" entries, or [] when the LLM is unset or unreachable."""
    if not is_configured():
        return []
    text = page_text[:MAX_TEXT_CHARS]
    headers = {"Content-Type": "application/json"}
    if os.environ.get("LLM_API_KEY", "").strip():
        headers["Authorization"] = f"Bearer {os.environ['LLM_API_KEY'].strip()}"
    body = {
        "model": os.environ["LLM_MODEL"].strip(),
        "messages": [{"role": "user", "content": PROMPT + text}],
        "temperature": 0,
    }
    url = os.environ["LLM_BASE_URL"].strip().rstrip("/") + "/chat/completions"
    request = Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            reply = json.loads(response.read().decode("utf-8"))["choices"][0]["message"]["content"]
    except (URLError, TimeoutError, OSError, ValueError, KeyError, IndexError) as exc:
        print(f"    LLM step skipped: {type(exc).__name__}: {exc}")
        return []
    return parse_people(reply, text)
