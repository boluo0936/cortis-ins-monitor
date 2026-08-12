"""
Cortis Instagram monitor - runs on GitHub Actions (overseas server, no GFW).
Fetches @cortis profile page and reports NEW posts via ServerChan (WeChat).

- Runs every 5 min via GitHub Actions cron.
- State persisted in seen.json (committed back by workflow).
- Prints nothing when no new posts (silent).
"""
import json
import os
import re
import sys
import urllib.request
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "seen.json")
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "")
IG_URL = "https://www.instagram.com/cortis/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"posts": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def extract_posts(html):
    """Extract post shortcodes + captions from the profile page.
    Modern IG embeds a JSON blob: "shortcode":"...","caption":{...},"taken_at_timestamp":...
    """
    posts = []
    # Pattern 1: __additionalDataLoaded JSON with timeline media
    for m in re.finditer(
        r'"(?:node|media)":\{[^{}]*?"shortcode":"([A-Za-z0-9_-]+)"[^{}]*?"(?:taken_at_timestamp|timestamp):(\d+)',
        html,
    ):
        posts.append({"shortcode": m.group(1), "ts": m.group(2)})
    # Pattern 2: generic shortcode + timestamp pairs
    if not posts:
        for m in re.finditer(r'"shortcode":"([A-Za-z0-9_-]+)"', html):
            posts.append({"shortcode": m.group(1), "ts": ""})
    # dedupe keep order
    seen = set()
    out = []
    for p in posts:
        if p["shortcode"] not in seen:
            seen.add(p["shortcode"])
            out.append(p)
    return out


def send_wechat(title, content):
    if not SERVERCHAN_KEY:
        print(f"[serverchan] no key, skipped: {title}", file=sys.stderr)
        return False
    data = urllib.parse.urlencode({"title": title, "desp": content}).encode("utf-8")
    req = urllib.request.Request(
        f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode("utf-8"))
        ok = resp.get("code") == 0
        print(f"[serverchan] {'OK' if ok else 'FAILED'}: {resp.get('message')}")
        return ok
    except Exception as e:
        print(f"[serverchan] error: {e}", file=sys.stderr)
        return False


def main():
    state = load_state()
    seen = set(state.get("posts", []))

    try:
        html = fetch(IG_URL)
    except Exception as e:
        sys.stderr.write(f"instagram page error: {e}\n")
        # If we can't fetch, don't mark anything seen - try again next tick
        print("")
        return

    # Detect login wall / challenge
    if "Login" in html and "shortcode" not in html:
        sys.stderr.write("instagram returned login wall or challenge page\n")
        print("")
        return

    posts = extract_posts(html)
    new_posts = [p for p in posts if p["shortcode"] not in seen]

    # persist seen FIRST
    for p in new_posts:
        seen.add(p["shortcode"])
    state["posts"] = list(seen)
    save_state(state)

    blocks = []
    for p in new_posts:
        url = f"https://www.instagram.com/p/{p['shortcode']}/"
        blocks.append(f"📸 Cortis 发 Ins 了！\n{url}")
    if blocks:
        # Also push via ServerChan directly (in case workflow delivery fails)
        for b in blocks:
            send_wechat("Cortis Instagram 更新", b)
        print("\n\n".join(blocks))


if __name__ == "__main__":
    main()
