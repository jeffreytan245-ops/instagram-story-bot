#!/usr/bin/env python3
"""
Post the next queued Instagram Story.

Designed to run unattended on GitHub Actions (hourly cron; posts only inside the
configured hour window) but also works locally or from Windows Task Scheduler.

Config comes from environment variables, falling back to a .env file next to
this script:

  IG_USER_ID        Instagram professional account ID            (required)
  IG_ACCESS_TOKEN   long-lived access token                       (required)
  GRAPH_HOST        graph.instagram.com (default) | graph.facebook.com
  GRAPH_VERSION     e.g. v23.0; empty = unversioned
  TIMEZONE          IANA zone for the schedule, e.g. Asia/Bangkok (default: system local)
  POST_HOUR         local hour to post (0-23). Unset = post whenever run.
  POST_WINDOW_HOURS how many hours after POST_HOUR a late run may still post (default 2)
  MEDIA_BASE_URL    prefix for queue items that use "file" instead of "url"
  TOKEN_OUT_FILE    if set, a refreshed token is written here (for CI to store)

Usage:
  python post_story.py                  # post next queued story (if inside window)
  python post_story.py --dry-run        # show what would be posted, no API calls
  python post_story.py --force          # ignore time window and once-per-day guard
  python post_story.py --refresh-token  # refresh the long-lived token now
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
QUEUE_FILE = ROOT / "queue.json"
STATE_FILE = ROOT / "state.json"
LOG_FILE = ROOT / "post_story.log"

TOKEN_REFRESH_AFTER_DAYS = 45      # long-lived tokens live 60 days
CONTAINER_POLL_SECONDS = 10
CONTAINER_POLL_LIMIT = 30          # 30 x 10s = 5 minutes


# ---------- helpers ----------

def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    # Real environment variables win over .env (this is how CI passes secrets).
    for key in ("IG_USER_ID", "IG_ACCESS_TOKEN", "GRAPH_HOST", "GRAPH_VERSION",
                "TIMEZONE", "POST_HOUR", "POST_WINDOW_HOURS", "MEDIA_BASE_URL",
                "TOKEN_OUT_FILE"):
        if os.environ.get(key):
            env[key] = os.environ[key].strip()
    for key in ("IG_USER_ID", "IG_ACCESS_TOKEN"):
        if not env.get(key):
            sys.exit(f"{key} is not set (environment variable or {ENV_FILE.name}).")
    env.setdefault("GRAPH_HOST", "graph.instagram.com")
    env.setdefault("GRAPH_VERSION", "")
    env.setdefault("POST_WINDOW_HOURS", "2")
    return env


def save_env_value(key: str, value: str) -> None:
    if not ENV_FILE.exists():
        return
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    out, found = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def local_now(env: dict) -> datetime:
    tz_name = env.get("TIMEZONE")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz_name))
        except Exception as e:  # noqa: BLE001
            log(f"Unknown TIMEZONE {tz_name!r} ({e}); using system local time.")
    return datetime.now()


def api(env: dict, method: str, path: str, params: dict) -> dict:
    base = f"https://{env['GRAPH_HOST']}/"
    if env["GRAPH_VERSION"]:
        base += env["GRAPH_VERSION"].strip("/") + "/"
    url = base + path.lstrip("/")
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(url + "?" + data.decode())
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {body}") from None


# ---------- token refresh ----------

def maybe_refresh_token(env: dict, state: dict, force: bool = False) -> None:
    stamp = state.get("token_refreshed_at")
    if stamp is None:
        # First run: assume the configured token is fresh.
        state["token_refreshed_at"] = datetime.now(timezone.utc).isoformat()
        save_json(STATE_FILE, state)
        if not force:
            return
    age = datetime.now(timezone.utc) - datetime.fromisoformat(state["token_refreshed_at"])
    if not force and age < timedelta(days=TOKEN_REFRESH_AFTER_DAYS):
        return
    if env["GRAPH_HOST"] != "graph.instagram.com":
        log("Token refresh only implemented for graph.instagram.com (Instagram Login). "
            "Refresh your Facebook-Login token manually.")
        return
    log("Refreshing long-lived access token...")
    res = api(env, "GET", "refresh_access_token",
              {"grant_type": "ig_refresh_token", "access_token": env["IG_ACCESS_TOKEN"]})
    new_token = res.get("access_token")
    if not new_token:
        raise RuntimeError(f"Refresh returned no token: {res}")
    env["IG_ACCESS_TOKEN"] = new_token
    save_env_value("IG_ACCESS_TOKEN", new_token)
    out_file = env.get("TOKEN_OUT_FILE")
    if out_file:
        Path(out_file).write_text(new_token, encoding="utf-8")
        log(f"New token written to {out_file} for the CI secret update step.")
    state["token_refreshed_at"] = datetime.now(timezone.utc).isoformat()
    save_json(STATE_FILE, state)
    log(f"Token refreshed (expires in ~{res.get('expires_in', '?')} s).")


# ---------- queue ----------

def pick_item(queue: dict, state: dict):
    items = queue.get("items", [])
    if not items:
        return None, None
    idx = state.get("next_index", 0)
    if idx >= len(items):
        if queue.get("mode", "sequential") == "loop":
            idx = 0
        else:
            return None, None
    return idx, items[idx]


def resolve_url(env: dict, item: dict) -> str:
    if item.get("url"):
        return item["url"]
    if item.get("file"):
        base = env.get("MEDIA_BASE_URL")
        if not base:
            raise RuntimeError('Queue item uses "file" but MEDIA_BASE_URL is not set.')
        return base.rstrip("/") + "/" + urllib.parse.quote(item["file"].lstrip("/"))
    raise RuntimeError(f'Queue item has neither "url" nor "file": {item}')


# ---------- publish ----------

def publish_story(env: dict, item: dict, url: str) -> str:
    kind = item.get("type", "video" if url.lower().endswith(".mp4") else "image").lower()
    params = {"media_type": "STORIES", "access_token": env["IG_ACCESS_TOKEN"]}
    params["video_url" if kind == "video" else "image_url"] = url

    res = api(env, "POST", f"{env['IG_USER_ID']}/media", params)
    container = res.get("id")
    if not container:
        raise RuntimeError(f"No container id returned: {res}")
    log(f"Container {container} created for {kind} {url}")

    for _ in range(CONTAINER_POLL_LIMIT):
        st = api(env, "GET", container,
                 {"fields": "status_code,status", "access_token": env["IG_ACCESS_TOKEN"]})
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Container {container} failed: {st}")
        time.sleep(CONTAINER_POLL_SECONDS)
    else:
        raise RuntimeError(f"Container {container} not ready after polling")

    pub = api(env, "POST", f"{env['IG_USER_ID']}/media_publish",
              {"creation_id": container, "access_token": env["IG_ACCESS_TOKEN"]})
    media_id = pub.get("id")
    if not media_id:
        raise RuntimeError(f"Publish returned no media id: {pub}")
    return media_id


# ---------- main ----------

def main(argv) -> int:
    dry_run = "--dry-run" in argv
    force = "--force" in argv
    refresh_only = "--refresh-token" in argv

    env = load_env()
    state = load_json(STATE_FILE, {"next_index": 0, "posted": []})
    queue = load_json(QUEUE_FILE, {"mode": "sequential", "items": []})

    if refresh_only:
        maybe_refresh_token(env, state, force=True)
        return 0

    now = local_now(env)
    today = now.strftime("%Y-%m-%d")

    if env.get("POST_HOUR") and not force and not dry_run:
        start = int(env["POST_HOUR"])
        end = start + int(env["POST_WINDOW_HOURS"])
        if not (start <= now.hour < end):
            log(f"Local time {now.strftime('%H:%M %Z')} is outside the "
                f"{start:02d}:00-{end:02d}:00 window; nothing to do.")
            return 0

    if state.get("last_posted_date") == today and not force and not dry_run:
        log("Already posted today; skipping (use --force to override).")
        return 0

    idx, item = pick_item(queue, state)
    if item is None:
        log("Queue is empty or exhausted. Add items to queue.json.")
        return 0

    try:
        url = resolve_url(env, item)
    except RuntimeError as e:
        log(f"FAILED: {e}")
        return 1

    if dry_run:
        log(f"[dry-run] Would post item #{idx}: {url}")
        return 0

    try:
        maybe_refresh_token(env, state)
        media_id = publish_story(env, item, url)
    except Exception as e:  # noqa: BLE001
        log(f"FAILED: {e}")
        return 1

    log(f"Posted story, media id {media_id}")
    state["next_index"] = idx + 1
    state["last_posted_date"] = today
    state.setdefault("posted", []).append(
        {"date": today, "index": idx, "url": url, "media_id": media_id})
    save_json(STATE_FILE, state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
