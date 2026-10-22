# SPDX-License-Identifier: Apache-2.0
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ERROR_BODY_CHARS = 300
MAX_TOKENS = 512
PLACEHOLDER = re.compile(r"\{(question|context)\}")


def user_message(template, item):
    values = {"question": item["question"], "context": item.get("context", "")}
    return PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


def post(url, payload, timeout):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def reply(item, setup):
    payload = {
        "model": setup["model"],
        "messages": [
            {"role": "system", "content": setup["system"]},
            {"role": "user", "content": user_message(setup["template"], item)},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.0,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "reply", "strict": True, "schema": setup["schema"]},
        },
    }
    record = {"id": item["id"], "schema": setup["schema"], "max_tokens": MAX_TOKENS}
    started = time.perf_counter()
    try:
        body = post(setup["url"], payload, setup["timeout"])
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:ERROR_BODY_CHARS]
        error = f"HTTP {exc.code}: {detail}"
    except (OSError, ValueError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    else:
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return {
            **record,
            "content": message.get("content"),
            "reasoning_content": message.get("reasoning_content"),
            "finish_reason": choice.get("finish_reason"),
            "usage": body.get("usage"),
            "timings": body.get("timings"),
            "wall_s": round(time.perf_counter() - started, 3),
        }
    return {
        **record,
        "error_stage": "llm",
        "error": error,
        "wall_s": round(time.perf_counter() - started, 3),
    }


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    job = json.loads(sys.stdin.read() or "{}")
    endpoint = job.get("endpoint") or os.environ.get("PROBE_ENDPOINT", "http://127.0.0.1:8080/v1")
    setup = {
        "url": endpoint.rstrip("/") + "/chat/completions",
        "model": os.environ.get("PROBE_MODEL", "local"),
        "timeout": float(os.environ.get("PROBE_TIMEOUT", "600")),
        "system": (HERE / "system.txt").read_text(encoding="utf-8"),
        "template": (HERE / "user.txt").read_text(encoding="utf-8"),
        "schema": json.loads((HERE / "schema.json").read_text(encoding="utf-8")),
    }
    if job.get("warmup"):
        print(f"[info] warmup (not scored): {job['warmup']}", file=sys.stderr, flush=True)
        reply({"id": "warmup", "question": job["warmup"]}, setup)
    items = job.get("items") or []
    for index, item in enumerate(items, 1):
        record = reply(item, setup)
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        print(
            f"[{index:3}/{len(items)}] {item['id']} {record.get('error') or record.get('finish_reason')}",
            file=sys.stderr,
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
