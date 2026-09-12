#!/usr/bin/env python3
"""
SAM.gov Opportunity Finder — Web UI

A friendly local website for the same tool find_opportunities.py runs
from the command line. Runs entirely on your machine: your SAM.gov API
key and Gmail credentials never leave it, and nothing here is reachable
from the internet unless you deliberately expose this port.

Run it:
    pip install -r requirements.txt -r webapp/requirements.txt
    python3 webapp/app.py
Then open http://localhost:8000 in your browser (the address is printed
on startup, so you can copy it straight from the terminal).

Port 8000, not 5000: on macOS, AirPlay Receiver holds port 5000 and
answers with a "403 Forbidden / not authorized" page, which looks like
a broken app but is really the OS answering instead of us. Override
with `PORT=9000 python3 webapp/app.py` if 8000 is taken too.

No terminal commands needed after that — paste your SAM.gov API key
into the Setup screen the first time you open the page, and everything
else (search, review packets, settings) happens by clicking around.
"""

import json
import os
import re
import sys

from flask import Flask, jsonify, request, send_from_directory

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import find_opportunities as core  # noqa: E402

SETTINGS_PATH = os.path.join(REPO_ROOT, "settings.json")
ENV_LOCAL_PATH = os.path.join(REPO_ROOT, ".env.local")
LAST_RESULTS_PATH = os.path.join(REPO_ROOT, "last_results.json")
DB_PATH = os.path.join(REPO_ROOT, core.DEFAULT_DB_PATH)
DRAFTS_DIR = os.path.join(REPO_ROOT, core.DEFAULT_DRAFTS_DIR)

DEFAULT_SETTINGS = {
    "company_name": "Proverbs 1821 Consulting LLC",
    "naics_codes": core.DEFAULT_NAICS,
    "certifications": ["wosb", "edwosb"],
    "posted_days": 45,
    "deadline_min_days": 7,
    "deadline_max_days": 60,
    "draft_min_score": 4,
    "show_ineligible": False,
    "generate_drafts": True,
    "notify_email": core.DEFAULT_TO_EMAIL,
    "send_email": True,
}


def load_env_file(path):
    """Loads KEY=VALUE lines into os.environ without overwriting anything
    already set (so real env vars / CI secrets always win over the local
    file)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def read_env_file_raw(path):
    lines = []
    if os.path.exists(path):
        with open(path) as f:
            lines = f.read().splitlines()
    return lines


def write_env_updates(path, updates):
    """Merges {KEY: value} into the .env.local file, replacing existing
    KEY= lines and appending new ones. Also applies to the live process
    env immediately so a restart isn't needed."""
    lines = read_env_file_raw(path)
    seen = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        new_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")

    with open(path, "w") as f:
        f.write("\n".join(new_lines) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    for key, value in updates.items():
        os.environ[key] = value


load_env_file(ENV_LOCAL_PATH)

app = Flask(__name__, static_folder="static", static_url_path="")


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as f:
            settings.update(json.load(f))
    return settings


def save_settings(settings):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def credential_status():
    return {
        "sam_api_key_set": bool(os.environ.get("SAM_API_KEY")),
        "gmail_configured": bool(os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD")),
    }


def serialize_result(pts, reasons, opp):
    pop = opp.get("placeOfPerformance") or {}
    return {
        "notice_id": opp.get("noticeId"),
        "score": pts,
        "reasons": reasons,
        "eligibility": core.eligibility(opp),
        "title": opp.get("title"),
        "naics": opp.get("naicsCode"),
        "psc": opp.get("classificationCode"),
        "set_aside": opp.get("typeOfSetAsideDescription"),
        "city": (pop.get("city") or {}).get("name"),
        "state": (pop.get("state") or {}).get("code"),
        "deadline": (opp.get("responseDeadLine") or "")[:10] or None,
        "link": opp.get("uiLink"),
    }


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/status")
def api_status():
    return jsonify(credential_status())


@app.route("/api/credentials", methods=["POST"])
def api_credentials():
    body = request.get_json(force=True) or {}
    updates = {}
    if body.get("sam_api_key"):
        updates["SAM_API_KEY"] = body["sam_api_key"].strip()
    if body.get("gmail_user"):
        updates["GMAIL_USER"] = body["gmail_user"].strip()
    if body.get("gmail_app_password"):
        updates["GMAIL_APP_PASSWORD"] = body["gmail_app_password"].strip()
    if updates:
        write_env_updates(ENV_LOCAL_PATH, updates)
    return jsonify(credential_status())


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    settings = load_settings()
    return jsonify({
        "settings": settings,
        "certification_options": [
            {"key": key, "label": info["label"]} for key, info in core.CERTIFICATION_HINTS.items()
        ],
    })


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    body = request.get_json(force=True) or {}
    settings = load_settings()

    if "company_name" in body:
        settings["company_name"] = str(body["company_name"]).strip() or settings["company_name"]

    if "naics_codes" in body:
        codes = [re.sub(r"[^0-9]", "", str(c)) for c in body["naics_codes"]]
        settings["naics_codes"] = [c for c in codes if c]

    if "certifications" in body:
        valid_keys = set(core.CERTIFICATION_HINTS.keys())
        settings["certifications"] = [c for c in body["certifications"] if c in valid_keys]

    for int_field, minimum in (
        ("posted_days", 1), ("deadline_min_days", 0),
        ("deadline_max_days", 1), ("draft_min_score", 0),
    ):
        if int_field in body:
            try:
                settings[int_field] = max(minimum, int(body[int_field]))
            except (TypeError, ValueError):
                pass

    for bool_field in ("show_ineligible", "generate_drafts", "send_email"):
        if bool_field in body:
            settings[bool_field] = bool(body[bool_field])

    if "notify_email" in body:
        email = str(body["notify_email"]).strip()
        if "@" in email:
            settings["notify_email"] = email

    save_settings(settings)
    return jsonify({"settings": settings})


@app.route("/api/search", methods=["POST"])
def api_search():
    api_key = os.environ.get("SAM_API_KEY")
    if not api_key:
        return jsonify({"ok": False, "error": "no_api_key"}), 400

    settings = load_settings()
    if not settings["naics_codes"]:
        return jsonify({"ok": False, "error": "no_naics_codes"}), 400

    eligible_hints, restricted_hints = core.build_hints(settings["certifications"])

    cfg = {
        "naics_codes": settings["naics_codes"],
        "posted_days": settings["posted_days"],
        "deadline_min": settings["deadline_min_days"],
        "deadline_max": settings["deadline_max_days"],
        "limit": 100,
        "max_retries": 4,
        "eligible_hints": eligible_hints,
        "restricted_hints": restricted_hints,
        "include_restricted": settings["show_ineligible"],
        "db_path": DB_PATH,
        "drafts_dir": DRAFTS_DIR,
        "draft_min_score": settings["draft_min_score"],
        "generate_drafts": settings["generate_drafts"],
        "to_email": settings["notify_email"],
        "from_email": os.environ.get("GMAIL_USER"),
        "app_password": os.environ.get("GMAIL_APP_PASSWORD"),
        "send_email": settings["send_email"],
    }

    log_lines = []
    try:
        result = core.run_search(cfg, api_key, log=log_lines.append)
    except Exception as e:
        return jsonify({"ok": False, "error": "search_failed", "detail": str(e), "log": log_lines}), 500

    ranked_json = [serialize_result(pts, reasons, opp) for pts, reasons, opp in result["ranked"]]
    new_ids = {opp.get("noticeId") for _, _, opp in result["new_ones"]}

    response = {
        "ok": True,
        "ranked": ranked_json,
        "new_notice_ids": list(new_ids),
        "excluded_restricted": result["excluded_restricted"],
        "draft_count": len(result["draft_paths"]),
        "emailed": result["emailed"],
        "log": log_lines,
    }
    with open(LAST_RESULTS_PATH, "w") as f:
        json.dump(response, f)
    return jsonify(response)


@app.route("/api/opportunities", methods=["GET"])
def api_last_opportunities():
    if os.path.exists(LAST_RESULTS_PATH):
        with open(LAST_RESULTS_PATH) as f:
            return jsonify(json.load(f))
    return jsonify({"ok": True, "ranked": [], "new_notice_ids": [], "excluded_restricted": 0, "draft_count": 0, "emailed": False, "log": []})


DRAFT_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.md$")


def draft_path_for(filename):
    if not DRAFT_FILENAME_RE.match(filename):
        return None
    path = os.path.join(DRAFTS_DIR, filename)
    return path if os.path.exists(path) else None


@app.route("/api/drafts", methods=["GET"])
def api_list_drafts():
    if not os.path.isdir(DRAFTS_DIR):
        return jsonify({"drafts": []})
    drafts = []
    for filename in sorted(os.listdir(DRAFTS_DIR)):
        if not filename.endswith(".md"):
            continue
        path = os.path.join(DRAFTS_DIR, filename)
        with open(path) as f:
            lines = f.read().splitlines()
        title = lines[0].lstrip("# ").strip() if lines else filename
        score_line = next((line for line in lines if line.startswith("- **Score:**")), "")
        total = sum(1 for line in lines if line.strip().startswith("- ["))
        done = sum(1 for line in lines if line.strip().startswith("- [x]") or line.strip().startswith("- [X]"))
        drafts.append({
            "filename": filename,
            "title": title,
            "score_line": score_line.replace("- **Score:**", "").strip(),
            "checklist_done": done,
            "checklist_total": total,
        })
    drafts.sort(key=lambda d: (d["checklist_total"] - d["checklist_done"] == 0, d["filename"]))
    return jsonify({"drafts": drafts})


@app.route("/api/drafts/<filename>", methods=["GET"])
def api_get_draft(filename):
    path = draft_path_for(filename)
    if not path:
        return jsonify({"ok": False, "error": "not_found"}), 404
    with open(path) as f:
        content = f.read()
    return jsonify({"ok": True, "filename": filename, "content": content})


@app.route("/api/drafts/<filename>/toggle", methods=["POST"])
def api_toggle_draft_line(filename):
    path = draft_path_for(filename)
    if not path:
        return jsonify({"ok": False, "error": "not_found"}), 404
    body = request.get_json(force=True) or {}
    try:
        line_index = int(body.get("line_index"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad_line_index"}), 400

    with open(path) as f:
        lines = f.read().splitlines()
    if not (0 <= line_index < len(lines)):
        return jsonify({"ok": False, "error": "bad_line_index"}), 400

    line = lines[line_index]
    if "- [ ]" in line:
        lines[line_index] = line.replace("- [ ]", "- [x]", 1)
    elif "- [x]" in line or "- [X]" in line:
        lines[line_index] = re.sub(r"- \[[xX]\]", "- [ ]", line, count=1)
    else:
        return jsonify({"ok": False, "error": "not_a_checklist_line"}), 400

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return jsonify({"ok": True, "content": "\n".join(lines)})


if __name__ == "__main__":
    # 8000 rather than Flask's usual 5000: macOS AirPlay Receiver owns 5000
    # and serves a 403 page there, which reads as "the app is broken".
    port = int(os.environ.get("PORT", "8000"))
    print(f"\n  Contract Finder is running — open this in your browser:\n\n      http://localhost:{port}\n")
    print("  (Leave this window open while you use it. Press Ctrl+C to stop.)\n")
    app.run(host="127.0.0.1", port=port, debug=False)
