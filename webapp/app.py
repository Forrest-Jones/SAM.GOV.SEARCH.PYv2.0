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

import csv
import hmac
import json
import os
import re
import sys
from datetime import date, datetime

from flask import Flask, jsonify, request, send_from_directory

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import company as fact_bank  # noqa: E402
import fillable  # noqa: E402
import find_opportunities as core  # noqa: E402
import packet as packet_builder  # noqa: E402
import proposal as proposal_builder  # noqa: E402

# Everything the app writes lives under DATA_DIR. Locally that's just the
# repo, but a deployed host's filesystem is wiped on every redeploy, so
# point DATA_DIR at a mounted volume there or the seen-notices history,
# review packets, and settings all reset. See DEPLOY.md.
DATA_DIR = os.environ.get("DATA_DIR", REPO_ROOT)
os.makedirs(DATA_DIR, exist_ok=True)

SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
ENV_LOCAL_PATH = os.path.join(DATA_DIR, ".env.local")

# Per-profile paths. The two businesses keep separate seen-notice history,
# review packets and cached results, so switching profiles in the UI shows
# one business's pipeline rather than both interleaved.
def db_path_for(profile):
    return os.path.join(DATA_DIR, f"state-{profile}.sqlite3")


def drafts_dir_for(profile):
    return os.path.join(DATA_DIR, core.DEFAULT_DRAFTS_DIR, profile)


def proposals_dir_for(profile):
    return os.path.join(DATA_DIR, "proposals", profile)


def notices_dir_for(profile):
    return os.path.join(DATA_DIR, "notices", profile)


def packets_dir_for(profile):
    return os.path.join(DATA_DIR, "packets", profile)


def last_results_path_for(profile):
    return os.path.join(DATA_DIR, f"last_results-{profile}.json")


# Settings shared across both businesses: one company, one inbox.
DEFAULT_SHARED = {
    "company_name": "Proverbs 1821 Consulting LLC",
    "notify_email": core.DEFAULT_TO_EMAIL,
    "send_email": True,
    # Fills the offeror/cover-letter sections of a proposal draft. Anything
    # left blank shows up as a visible [[FILL: ...]] blank rather than being
    # guessed at — these are facts that go on a federal submission.
    "company_profile": dict(proposal_builder.DEFAULT_COMPANY_PROFILE),
}

# Settings that differ per business.
PER_PROFILE_KEYS = (
    "naics_codes", "posted_days", "deadline_min_days",
    "deadline_max_days", "draft_min_score", "show_ineligible", "generate_drafts",
)


def default_profile_settings(profile):
    spec = core.PROFILES[profile]
    return {
        "naics_codes": list(spec["naics"]),

        "posted_days": 45,
        "deadline_min_days": 7,
        "deadline_max_days": 60,
        "draft_min_score": spec["draft_min_score"],
        "show_ineligible": False,
        "generate_drafts": True,
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


@app.before_request
def require_password():
    """Password-gates the whole app when APP_PASSWORD is set.

    Unset (the local default) leaves the app open, which is fine when it's
    only listening on 127.0.0.1. A deployed copy is reachable by anyone
    who finds the URL, and it holds a live SAM.gov key and this business's
    pipeline — so a deploy without APP_PASSWORD refuses to serve rather
    than quietly publishing all of it.
    """
    if request.path == "/healthz":
        return None  # platform health checks don't carry credentials

    expected = os.environ.get("APP_PASSWORD")

    if not expected:
        if os.environ.get("PUBLIC_DEPLOY") == "1":
            return (
                "APP_PASSWORD is not set. Refusing to serve a public deployment "
                "with no password — set APP_PASSWORD in this host's environment "
                "variables and redeploy.",
                500,
            )
        return None

    auth = request.authorization
    if auth and hmac.compare_digest(auth.password or "", expected):
        return None
    return (
        "Sign in required.",
        401,
        {"WWW-Authenticate": 'Basic realm="Contract Finder"'},
    )


def load_store():
    """The whole settings file: shared keys plus one block per profile.

    A pre-profiles settings.json was a flat dict; it gets migrated into the
    p1821 block rather than discarded, since that's the business those
    settings described."""
    store = {
        **DEFAULT_SHARED,
        "active_profile": core.DEFAULT_PROFILE,
        "profiles": {p: default_profile_settings(p) for p in core.PROFILES},
    }
    if not os.path.exists(SETTINGS_PATH):
        return store

    with open(SETTINGS_PATH) as f:
        saved = json.load(f)

    if "profiles" not in saved:
        for key in DEFAULT_SHARED:
            if key in saved:
                store[key] = saved[key]
        migrated = {k: saved[k] for k in PER_PROFILE_KEYS if k in saved}
        store["profiles"][core.DEFAULT_PROFILE].update(migrated)
        return store

    for key in DEFAULT_SHARED:
        if key in saved:
            store[key] = saved[key]
    if saved.get("active_profile") in core.PROFILES:
        store["active_profile"] = saved["active_profile"]
    for profile, block in (saved.get("profiles") or {}).items():
        if profile in store["profiles"] and isinstance(block, dict):
            store["profiles"][profile].update(
                {k: v for k, v in block.items() if k in PER_PROFILE_KEYS}
            )
    # A settings file written before certifications moved out still carries
    # them, and "certifications" is no longer in PER_PROFILE_KEYS so the
    # loop above already drops it. Stripped from the file too, so nothing
    # reads a stale copy: a WOSB sole source scored "Great Match — eligible"
    # in the web UI for two days after the code stopped claiming WOSB,
    # because this file still said the certification was held.
    dropped = "certifications" in saved
    for block in (saved.get("profiles") or {}).values():
        if isinstance(block, dict) and "certifications" in block:
            dropped = True
    if dropped:
        save_store(store)
    return store


def save_store(store):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(store, f, indent=2)


def load_settings(profile=None):
    """Flattened view for one profile: shared keys plus that profile's own."""
    store = load_store()
    profile = profile if profile in core.PROFILES else store["active_profile"]
    settings = {key: store[key] for key in DEFAULT_SHARED}
    settings.update(store["profiles"][profile])
    settings["profile"] = profile
    return settings


def requested_profile():
    """Profile for this request: ?profile= or JSON body, else the active one."""
    candidate = request.args.get("profile")
    if not candidate and request.is_json:
        candidate = (request.get_json(silent=True) or {}).get("profile")
    if candidate in core.PROFILES:
        return candidate
    return load_store()["active_profile"]


def credential_status():
    return {
        "sam_api_key_set": bool(os.environ.get("SAM_API_KEY")),
        "gmail_configured": bool(os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD")),
    }


def serialize_result(pts, reasons, opp, held_certs=None):
    pop = opp.get("placeOfPerformance") or {}
    return {
        "notice_id": opp.get("noticeId"),
        "score": pts,
        "reasons": reasons,
        # Judged against DEFAULT_HELD_CERTS, the one place that records what
        # badge matches this business rather than the module default.
        "eligibility": core.eligibility(opp, held_certs) if held_certs is not None else core.eligibility(opp),
        "title": opp.get("title"),
        "naics": opp.get("naicsCode"),
        "psc": opp.get("classificationCode"),
        "set_aside": opp.get("typeOfSetAsideDescription"),
        "city": (pop.get("city") or {}).get("name"),
        "state": (pop.get("state") or {}).get("code"),
        "deadline": (opp.get("responseDeadLine") or "")[:10] or None,
        "link": opp.get("uiLink"),
    }


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/favicon.svg")
def favicon():
    return send_from_directory(app.static_folder, "favicon.svg")


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


def held_certifications():
    """What the business holds, and where that is recorded. Read-only on
    purpose: a checkbox that can re-enable WOSB is a checkbox that will
    eventually put a false certification on a federal submission."""
    return {
        "held": list(core.DEFAULT_HELD_CERTS),
        "labels": {k: v["label"] for k, v in core.CERTIFICATION_HINTS.items()},
        "source": "DEFAULT_HELD_CERTS in find_opportunities.py",
    }


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    profile = requested_profile()
    return jsonify({
        "settings": load_settings(profile),
        "active_profile": profile,
        "profiles": [
            {"key": key, "label": spec["label"]} for key, spec in core.PROFILES.items()
        ],
        "certifications": held_certifications(),
    })


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    body = request.get_json(force=True) or {}
    store = load_store()
    profile = requested_profile()
    if body.get("switch_to") in core.PROFILES:
        store["active_profile"] = body["switch_to"]
        save_store(store)
        return jsonify({"settings": load_settings(store["active_profile"]),
                        "active_profile": store["active_profile"]})

    settings = {**{k: store[k] for k in DEFAULT_SHARED}, **store["profiles"][profile]}

    if "company_name" in body:
        settings["company_name"] = str(body["company_name"]).strip() or settings["company_name"]

    if "naics_codes" in body:
        codes = [re.sub(r"[^0-9]", "", str(c)) for c in body["naics_codes"]]
        settings["naics_codes"] = [c for c in codes if c]


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

    if isinstance(body.get("company_profile"), dict):
        profile = dict(settings.get("company_profile") or {})
        for key in proposal_builder.DEFAULT_COMPANY_PROFILE:
            if key in body["company_profile"]:
                profile[key] = str(body["company_profile"][key]).strip()
        settings["company_profile"] = profile

    for key in DEFAULT_SHARED:
        store[key] = settings[key]
    store["profiles"][profile] = {k: settings[k] for k in PER_PROFILE_KEYS}
    save_store(store)
    settings["profile"] = profile
    return jsonify({"settings": settings, "active_profile": store["active_profile"]})


@app.route("/api/search", methods=["POST"])
def api_search():
    api_key = os.environ.get("SAM_API_KEY")
    if not api_key:
        return jsonify({"ok": False, "error": "no_api_key"}), 400

    profile = requested_profile()
    settings = load_settings(profile)
    if not settings["naics_codes"]:
        return jsonify({"ok": False, "error": "no_naics_codes"}), 400
    spec = core.PROFILES[profile]

    cfg = {
        "naics_codes": settings["naics_codes"],
        "posted_days": settings["posted_days"],
        "deadline_min": settings["deadline_min_days"],
        "deadline_max": settings["deadline_max_days"],
        "limit": 100,
        "max_retries": 4,
        # One source of truth, in code, tested. Not a saved setting anyone
        # can leave stale.
        "held_certs": list(core.DEFAULT_HELD_CERTS),
        "include_restricted": settings["show_ineligible"],
        "include_expired": False,
        "keywords": spec["keywords"],
        "priority_psc": spec["priority_psc"],
        "home_states": spec["home_states"],
        "profile_label": spec["label"],
        "db_path": db_path_for(profile),
        "drafts_dir": drafts_dir_for(profile),
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

    ranked_json = [
        serialize_result(pts, reasons, opp, list(core.DEFAULT_HELD_CERTS))
        for pts, reasons, opp in result["ranked"]
    ]
    new_ids = {opp.get("noticeId") for _, _, opp in result["new_ones"]}

    # Stash the raw notice (plus the description already fetched during the
    # search) so "Build proposal draft" can run later without another API call.
    notices_dir = notices_dir_for(profile)
    os.makedirs(notices_dir, exist_ok=True)
    for pts, reasons, opp in result["new_ones"]:
        nid = opp.get("noticeId")
        if not nid or not re.match(r"^[A-Za-z0-9_.-]+$", nid):
            continue
        with open(os.path.join(notices_dir, f"{nid}.json"), "w") as f:
            json.dump({
                "opp": opp,
                "score": pts,
                "reasons": reasons,
                "description": result["descriptions"].get(nid),
            }, f)

    response = {
        "ok": True,
        "ranked": ranked_json,
        "new_notice_ids": list(new_ids),
        "excluded_restricted": result["excluded_restricted"],
        "excluded_expired": result["excluded_expired"],
        "excluded_supplies": result["excluded_supplies"],
        "draft_count": len(result["draft_paths"]),
        "emailed": result["emailed"],
        "log": log_lines,
    }
    response["profile"] = profile
    with open(last_results_path_for(profile), "w") as f:
        json.dump(response, f)
    return jsonify(response)


@app.route("/api/opportunities", methods=["GET"])
def api_last_opportunities():
    cached = last_results_path_for(requested_profile())
    if os.path.exists(cached):
        with open(cached) as f:
            return jsonify(json.load(f))
    return jsonify({"ok": True, "ranked": [], "new_notice_ids": [], "excluded_restricted": 0, "draft_count": 0, "emailed": False, "log": []})


NOTICE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
DRAFT_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.md$")


@app.route("/api/proposals/<notice_id>", methods=["POST"])
def api_build_proposal(notice_id):
    """Builds a proposal draft for one cached notice. Writes a file and
    returns its text — it does not and cannot submit anything."""
    if not NOTICE_ID_RE.match(notice_id):
        return jsonify({"ok": False, "error": "bad_notice_id"}), 400
    profile = requested_profile()
    notice_path = os.path.join(notices_dir_for(profile), f"{notice_id}.json")
    if not os.path.exists(notice_path):
        return jsonify({"ok": False, "error": "notice_not_cached"}), 404

    with open(notice_path) as f:
        cached = json.load(f)

    settings = load_settings(profile)
    path = proposal_builder.write_proposal(
        cached["opp"],
        cached.get("description"),
        settings.get("company_profile") or {},
        proposals_dir_for(profile),
        score=cached.get("score"),
        reasons=cached.get("reasons") or "",
    )
    with open(path) as f:
        content = f.read()
    return jsonify({
        "ok": True,
        "filename": os.path.basename(path),
        "content": content,
        "blanks": content.count("[[FILL:"),
    })


@app.route("/api/proposals", methods=["GET"])
def api_list_proposals():
    proposals_dir = proposals_dir_for(requested_profile())
    if not os.path.isdir(proposals_dir):
        return jsonify({"proposals": []})
    out = []
    for filename in sorted(os.listdir(proposals_dir)):
        if not filename.endswith(".md"):
            continue
        with open(os.path.join(proposals_dir, filename)) as f:
            content = f.read()
        first = content.split("\n", 1)[0]
        out.append({
            "filename": filename,
            "title": first.lstrip("# ").replace("Proposal Draft — ", "").strip(),
            "blanks": content.count("[[FILL:"),
        })
    return jsonify({"proposals": out})


@app.route("/api/proposals/<filename>", methods=["GET"])
def api_get_proposal(filename):
    if not DRAFT_FILENAME_RE.match(filename):
        return jsonify({"ok": False, "error": "not_found"}), 404
    path = os.path.join(proposals_dir_for(requested_profile()), filename)
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "not_found"}), 404
    with open(path) as f:
        return jsonify({"ok": True, "filename": filename, "content": f.read()})


def draft_path_for(filename):
    if not DRAFT_FILENAME_RE.match(filename):
        return None
    path = os.path.join(drafts_dir_for(requested_profile()), filename)
    return path if os.path.exists(path) else None


def cached_notice_ids():
    notices_dir = notices_dir_for(requested_profile())
    if not os.path.isdir(notices_dir):
        return []
    return [f[:-5] for f in os.listdir(notices_dir) if f.endswith(".json")]


def notice_id_for_draft(filename, notice_ids):
    """Drafts are named '<noticeId>-<slug>.md' and a notice ID can itself
    contain hyphens, so match by longest cached ID that prefixes the
    filename rather than splitting on the first '-'."""
    matches = [nid for nid in notice_ids if filename.startswith(nid + "-")]
    return max(matches, key=len) if matches else None


PACKET_FOLDER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
PACKET_FILES = {
    "start_here": "00-START-HERE.md",
    "proposal": "01-proposal.md",
    "price": "02-price-sheet.csv",
    "email": "03-quote-email.txt",
}


def packet_path(folder, name=None):
    """Resolves a packet folder (and optionally a file inside it) under the
    current profile's tray, refusing anything that escapes it."""
    if not PACKET_FOLDER_RE.match(folder or "") or ".." in folder:
        return None
    root = os.path.realpath(packets_dir_for(requested_profile()))
    out = os.path.realpath(os.path.join(root, folder))
    if not out.startswith(root + os.sep) or not os.path.isdir(out):
        return None
    if name is None:
        return out
    target = os.path.realpath(os.path.join(out, name))
    return target if target.startswith(out + os.sep) else None


def parse_price_sheet(path):
    """The price sheet as rows the browser can edit. Formulas are dropped:
    the browser computes extended values live, and a stored "=C5*D5" is
    meaningless to it."""
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, newline="") as f:
        for record in csv.reader(f):
            if len(record) >= 5 and record[0] and record[0] not in ("Labor category", "TOTAL"):
                rows.append({
                    "category": record[0], "unit": record[1] or "hr",
                    "rate": record[2], "hours": record[3],
                })
            elif len(record) >= 5 and record[1] == "hr" and not record[0]:
                rows.append({"category": "", "unit": "hr", "rate": record[2], "hours": record[3]})
    return rows


def write_price_rows(path, title, solicitation, rows):
    """Writes the sheet back with live formulas restored, so it still opens
    as a working spreadsheet outside the browser."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"PRICE SHEET — {title}"])
        w.writerow([f"Solicitation: {solicitation}"])
        w.writerow([])
        w.writerow(["Labor category", "Unit", "Rate", "Hours / Qty", "Extended"])
        first = 5
        for i, row in enumerate(rows, start=first):
            w.writerow([row.get("category", ""), row.get("unit") or "hr",
                        row.get("rate", ""), row.get("hours", ""), f"=C{i}*D{i}"])
        last = first + len(rows) - 1
        w.writerow([])
        w.writerow(["TOTAL", "", "", "", f"=SUM(E{first}:E{last})" if rows else ""])
    return path


def packet_summary(folder, path):
    """Everything the tray list needs, read off disk rather than from the
    index file, so a packet edited by hand still reports honestly."""
    proposal_path = os.path.join(path, PACKET_FILES["proposal"])
    text = ""
    if os.path.exists(proposal_path):
        with open(proposal_path) as f:
            text = f.read()
    meta = {}
    meta_path = os.path.join(path, ".packet-meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except ValueError:
            meta = {}

    deadline = meta.get("deadline") or ""
    days = None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", deadline):
        days = (datetime.strptime(deadline, "%Y-%m-%d").date() - date.today()).days

    title = ""
    start_here = os.path.join(path, PACKET_FILES["start_here"])
    if os.path.exists(start_here):
        with open(start_here) as f:
            title = f.readline().lstrip("# ").strip()

    attachments = []
    att_dir = os.path.join(path, "attachments")
    if os.path.isdir(att_dir):
        attachments = sorted(f for f in os.listdir(att_dir)
                             if f not in ("MANIFEST.txt", "PRUNED.txt"))

    return {
        "folder": folder,
        "title": title or folder,
        "deadline": deadline or None,
        "days": days,
        "blanks": fillable.progress(text) if text else None,
        "attachments": len(attachments),
        "built": meta.get("built"),
    }


@app.route("/api/packets", methods=["GET"])
def api_list_packets():
    """The tray, soonest deadline first."""
    root = packets_dir_for(requested_profile())
    if not os.path.isdir(root):
        return jsonify({"packets": []})
    out = []
    for folder in sorted(os.listdir(root)):
        path = os.path.join(root, folder)
        if os.path.isdir(path) and os.path.exists(os.path.join(path, PACKET_FILES["start_here"])):
            out.append(packet_summary(folder, path))
    out.sort(key=lambda p: (p["deadline"] or "9999-99-99"))
    return jsonify({"packets": out})


@app.route("/api/packets/<folder>", methods=["GET"])
def api_get_packet(folder):
    """One packet, opened for work: the checklist, the blanks as an
    addressable list, the price rows, the cover email and the
    solicitation's own documents."""
    path = packet_path(folder)
    if not path:
        return jsonify({"ok": False, "error": "not_found"}), 404

    def read(name):
        target = os.path.join(path, name)
        if not os.path.exists(target):
            return ""
        with open(target) as f:
            return f.read()

    proposal_text = read(PACKET_FILES["proposal"])
    summary = packet_summary(folder, path)
    att_dir = os.path.join(path, "attachments")
    attachments = []
    if os.path.isdir(att_dir):
        for name in sorted(os.listdir(att_dir)):
            if name in ("MANIFEST.txt", "PRUNED.txt"):
                continue
            attachments.append({
                "name": name,
                "size": os.path.getsize(os.path.join(att_dir, name)),
            })

    return jsonify({
        "ok": True,
        "summary": summary,
        "start_here": read(PACKET_FILES["start_here"]),
        "proposal": proposal_text,
        "blanks": fillable.blanks(proposal_text),
        "price_rows": parse_price_sheet(os.path.join(path, PACKET_FILES["price"])),
        "email": read(PACKET_FILES["email"]),
        "attachments": attachments,
        "manifest": read(os.path.join("attachments", "MANIFEST.txt")),
    })


@app.route("/api/packets/<folder>/fill", methods=["POST"])
def api_fill_packet(folder):
    """Writes answers into the packet's own markdown.

    There is no separate copy of the document: the file on disk stays the
    single source of truth, so what you see on GitHub, in the folder and in
    the browser can never disagree.
    """
    path = packet_path(folder, PACKET_FILES["proposal"])
    if not path or not os.path.exists(path):
        return jsonify({"ok": False, "error": "not_found"}), 404

    answers = (request.get_json(silent=True) or {}).get("answers") or {}
    with open(path) as f:
        text = f.read()
    try:
        updated = fillable.fill(text, answers)
    except fillable.FillMismatch as e:
        # The page was rendered against a different version of the file.
        # Refusing is the whole point: a price written into the wrong field
        # on a federal submission is not a cosmetic bug.
        return jsonify({"ok": False, "error": "stale", "detail": str(e)}), 409

    with open(path, "w") as f:
        f.write(updated)
    return jsonify({
        "ok": True,
        "blanks": fillable.blanks(updated),
        "remaining": fillable.progress(updated),
        "proposal": updated,
    })


@app.route("/api/packets/<folder>/price", methods=["POST"])
def api_save_price(folder):
    path = packet_path(folder, PACKET_FILES["price"])
    if not path:
        return jsonify({"ok": False, "error": "not_found"}), 404
    body = request.get_json(silent=True) or {}
    rows = body.get("rows") or []
    summary = packet_summary(folder, packet_path(folder))
    write_price_rows(path, summary["title"], body.get("solicitation") or "", rows)

    # The proposal carries its own price table. Left alone it would show two
    # dozen bare blanks labelled "category", "hours", "$rate" — a second,
    # worse copy of the sheet just filled in. One price, entered once.
    proposal_path = packet_path(folder, PACKET_FILES["proposal"])
    remaining = None
    if proposal_path and os.path.exists(proposal_path):
        with open(proposal_path) as f:
            text = f.read()
        updated = fillable.write_price_table(text, rows)
        with open(proposal_path, "w") as f:
            f.write(updated)
        remaining = fillable.progress(updated)
        blanks = fillable.blanks(updated)
    else:
        blanks = []

    return jsonify({"ok": True, "rows": parse_price_sheet(path),
                    "blanks": blanks, "remaining": remaining})


@app.route("/api/packets/<folder>/file/<path:name>", methods=["GET"])
def api_packet_file(folder, name):
    """Serves a packet file — including the solicitation's own attachments,
    so the PWS can be opened from the page instead of hunted for on disk."""
    base = packet_path(folder)
    if not base:
        return jsonify({"ok": False, "error": "not_found"}), 404
    target = packet_path(folder, name)
    if not target or not os.path.isfile(target):
        return jsonify({"ok": False, "error": "not_found"}), 404
    return send_from_directory(os.path.dirname(target), os.path.basename(target))


@app.route("/api/factbank", methods=["GET"])
def api_factbank():
    """What the fact bank still lacks, so the page can say why blanks keep
    reappearing instead of leaving the user to wonder."""
    profile = requested_profile()
    company = fact_bank.load_company(profile)
    required, leverage = fact_bank.missing_fields(company)
    return jsonify({
        "profile": profile,
        "required_missing": required,
        "leverage_missing": leverage,
        "format_warnings": fact_bank.format_warnings(company),
        "past_performance": len(fact_bank.filled_rows(company, "past_performance")),
        "rate_card": len(fact_bank.filled_rows(company, "rate_card")),
        "ready": not required,
    })


@app.route("/api/drafts", methods=["GET"])
def api_list_drafts():
    drafts_dir = drafts_dir_for(requested_profile())
    if not os.path.isdir(drafts_dir):
        return jsonify({"drafts": []})
    notice_ids = cached_notice_ids()
    drafts = []
    for filename in sorted(os.listdir(drafts_dir)):
        if not filename.endswith(".md"):
            continue
        path = os.path.join(drafts_dir_for(requested_profile()), filename)
        with open(path) as f:
            lines = f.read().splitlines()
        title = lines[0].lstrip("# ").strip() if lines else filename
        score_line = next((line for line in lines if line.startswith("- **Score:**")), "")
        total = sum(1 for line in lines if line.strip().startswith("- ["))
        done = sum(1 for line in lines if line.strip().startswith("- [x]") or line.strip().startswith("- [X]"))
        drafts.append({
            "filename": filename,
            "notice_id": notice_id_for_draft(filename, notice_ids),
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
