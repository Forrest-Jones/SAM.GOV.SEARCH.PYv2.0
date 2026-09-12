#!/usr/bin/env python3
"""
Bid packet builder — the conveyor belt.

proposal.py writes one document. This wraps it into a folder that is a
day's work already done: the draft, a price sheet with your rates already
in it, a ready-to-send email to the contracting officer, the
solicitation's own attachments, and a one-page START-HERE that says
exactly what is left for a human and in what order.

The division of labor is fixed and deliberate:

  the machine does   finding, filtering, identity, boilerplate, rates,
                     past performance, formatting, the paper trail
  only you can do    the go/no-go call, the price, the signature

Nothing here submits anything. There is no SAM.gov submission API, and a
federal offer carries signed representations and certifications — a
machine signing those on your behalf is a false statement, not a feature.
"""

import csv
import hashlib
import json
import os
import re
from datetime import date, datetime

import proposal
from company import filled_rows

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024

META_NAME = ".packet-meta.json"
GENERATED = ("00-START-HERE.md", "01-proposal.md", "02-price-sheet.csv", "03-quote-email.txt")


def _deadline_parts(opp):
    """(iso date string, days remaining or None)."""
    raw = opp.get("responseDeadLine") or ""
    if not raw:
        return "unknown", None
    iso = raw[:10]
    try:
        days = (datetime.strptime(iso, "%Y-%m-%d").date() - date.today()).days
    except ValueError:
        return iso, None
    return iso, days


def _co_email(opp):
    for contact in opp.get("pointOfContact") or []:
        if contact.get("email"):
            return contact["email"]
    return ""


def _co_name(opp):
    for contact in opp.get("pointOfContact") or []:
        if contact.get("fullName"):
            return contact["fullName"]
    return ""


def company_fingerprint(company):
    """A stable hash of the facts a packet was built from, so a rebuild can
    tell that the fact bank has changed since."""
    facts = {k: v for k, v in (company or {}).items() if not k.startswith("_")}
    blob = json.dumps(facts, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _file_hash(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return None


def _read_meta(out):
    try:
        with open(os.path.join(out, META_NAME)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def untouched_files(out, meta):
    """Which generated files are still exactly as this tool wrote them.

    The point is to distinguish "nobody has opened this yet" from "priced
    and edited". A file whose content still hashes to what was recorded at
    build time is the machine's to replace; anything else is the user's
    work and is never overwritten.
    """
    recorded = (meta or {}).get("files") or {}
    return {
        name for name in GENERATED
        if name in recorded and _file_hash(os.path.join(out, name)) == recorded[name]
    }


def packet_dir(opp, root):
    nid = opp.get("noticeId") or "unknown"
    return os.path.join(root, f"{nid}-{proposal.slugify(opp.get('title'))}")


def write_price_sheet(opp, company, path):
    """A CSV that opens straight into Excel or Sheets, with the rate card
    already filled in. Hours are the only genuinely per-solicitation
    number, so hours are the only empty column."""
    rows = filled_rows(company, "rate_card")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"PRICE SHEET — {opp.get('title') or ''}"])
        w.writerow([f"Solicitation: {opp.get('solicitationNumber') or opp.get('noticeId') or ''}"])
        w.writerow([])
        w.writerow(["Labor category", "Unit", "Rate", "Hours / Qty", "Extended"])
        if rows:
            for i, row in enumerate(rows, start=5):
                # A live formula, so the extended column totals itself the
                # moment hours are typed in.
                w.writerow([row.get("category"), row.get("unit") or "hr",
                            row.get("rate"), "", f"=C{i}*D{i}"])
            last = 4 + len(rows)
            w.writerow([])
            w.writerow(["TOTAL", "", "", "", f"=SUM(E5:E{last})"])
        else:
            for _ in range(4):
                w.writerow(["", "hr", "", "", ""])
            w.writerow([])
            w.writerow(["TOTAL", "", "", "", ""])
            w.writerow([])
            w.writerow(["No rate card on file — add [[profile.rate_card]] entries to",
                        "company.toml and every future price sheet fills its own rates."])
        w.writerow([])
        w.writerow(["Other direct costs (travel, materials):", ""])
        w.writerow(["Basis of estimate:", ""])
        w.writerow(["Offer valid for (days):", ""])
    return path


def build_quote_email(opp, company):
    """The cover email, addressed and subject-lined off the notice itself.
    Left as a .txt to be read, edited and sent by a person — it is not
    wired to an outbox."""
    sol = opp.get("solicitationNumber") or opp.get("noticeId") or ""
    title = opp.get("title") or ""
    co_email = _co_email(opp) or "[[FILL: contracting officer email — read it off the listing]]"
    co_name = _co_name(opp) or "[[FILL: Contracting Officer name]]"
    legal = company.get("legal_name") or "[[FILL: legal business name]]"
    uei = company.get("uei") or "[[FILL: UEI]]"
    cage = company.get("cage") or "[[FILL: CAGE]]"
    signer = company.get("signatory_name") or "[[FILL: signatory name]]"
    title_of = company.get("signatory_title") or "[[FILL: title]]"
    phone = company.get("phone") or "[[FILL: phone]]"
    email = company.get("email") or "[[FILL: email]]"
    deadline, _ = _deadline_parts(opp)

    return f"""To:      {co_email}
Subject: {sol} — Quote from {legal} (UEI {uei})

{co_name},

{legal} is pleased to submit the attached quote in response to {sol},
{title}. We have reviewed the requirement in full and confirm our ability
to perform within the stated period and place of performance.

  Offeror:  {legal}
  UEI:      {uei}
  CAGE:     {cage}
  Contact:  {signer}, {title_of} — {phone}, {email}

Attached:
  - Price sheet, signed
  - [[FILL: any other attachment the solicitation requires — check its
    instructions paragraph before sending]]

Our representations and certifications are current in SAM.gov.

Please confirm receipt. We are available for any clarification you need
before the {deadline} closing.

Respectfully,
{signer}
{title_of}, {legal}
{phone} | {email}

--------------------------------------------------------------------
BEFORE SENDING, CHECK:
  [ ] This is the submission method the solicitation actually names.
      Some require a portal, a specific form, or a different address.
      Do not assume email.
  [ ] The price sheet is signed by the authorized signatory.
  [ ] Sent before {deadline} — confirm the closing TIME and time zone.
--------------------------------------------------------------------
"""


def fetch_attachments(opp, dest_dir, session=None, log=print):
    """Downloads the solicitation's own files next to the draft, because
    the PWS and the forms are what actually have to be answered.

    Always writes MANIFEST.txt with every URL, so the packet records what
    exists even when the download is blocked — the SAM.gov host is not
    reachable from every environment, and a missing file must never look
    like a notice with no attachments.
    """
    links = [u for u in (opp.get("resourceLinks") or []) if u]
    os.makedirs(dest_dir, exist_ok=True)
    manifest = os.path.join(dest_dir, "MANIFEST.txt")
    got, failed = [], []

    if session is not None:
        for url in links:
            name = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(url.split("?")[0]))[:80]
            name = name or f"attachment-{len(got) + len(failed) + 1}"
            try:
                resp = session.get(url, timeout=60)
                resp.raise_for_status()
                if len(resp.content) > MAX_ATTACHMENT_BYTES:
                    failed.append((url, "larger than 15MB — download it by hand"))
                    continue
                with open(os.path.join(dest_dir, name), "wb") as f:
                    f.write(resp.content)
                got.append((url, name))
            except Exception as e:  # a blocked download must not fail the packet
                failed.append((url, str(e)[:120]))

    with open(manifest, "w") as f:
        f.write(f"Attachments listed on SAM.gov notice {opp.get('noticeId') or 'unknown'}\n")
        f.write(f"Listing: {opp.get('uiLink') or 'unknown'}\n\n")
        if not links:
            f.write("The notice lists no attachments via the API.\n")
            f.write("Open the listing anyway — some agencies post documents\n")
            f.write("only inside the notice body or a separate portal.\n")
        for url, name in got:
            f.write(f"[downloaded] {name}\n             {url}\n")
        for url, why in failed:
            f.write(f"[NOT downloaded — get it yourself] {url}\n    reason: {why}\n")
    return got, failed


def build_start_here(opp, company, blanks_left, attachments, failed):
    deadline, days = _deadline_parts(opp)
    when = f"{deadline}"
    if days is not None:
        when += f" ({days} days out)" if days >= 0 else f" (PASSED {abs(days)} days ago)"
    pop = opp.get("placeOfPerformance") or {}
    where = ", ".join(
        p for p in ((pop.get("city") or {}).get("name"), (pop.get("state") or {}).get("code")) if p
    ) or "see listing"
    co_email = _co_email(opp) or "not published — read it off the listing"
    rate_card = filled_rows(company, "rate_card")
    refs = filled_rows(company, "past_performance")

    lines = [
        f"# {opp.get('title') or 'Untitled notice'}",
        "",
        "| | |",
        "|---|---|",
        f"| **Due** | **{when}** |",
        f"| Solicitation | {opp.get('solicitationNumber') or opp.get('noticeId') or '-'} |",
        f"| Agency | {opp.get('fullParentPathName') or '-'} |",
        f"| Set-aside | {opp.get('typeOfSetAsideDescription') or 'None (full and open)'} |",
        f"| NAICS / PSC | {opp.get('naicsCode') or '-'} / {opp.get('classificationCode') or '-'} |",
        f"| Where | {where} |",
        f"| Contracting officer | {co_email} |",
        f"| Listing | {opp.get('uiLink') or '-'} |",
        "",
        "## Your five steps",
        "",
        "**1. Read it.** Open the listing above and everything in `attachments/`.",
        "",
        "**2. Go or no-go.** Can you actually perform this work, at this place, by",
        "this date? If no, delete this folder and add a line to `skip_keywords` in",
        "`company.toml` so it never reaches you again.",
        "",
        "**3. Price it.** Open `02-price-sheet.csv`. Your rates are already in it"
        + (f" ({len(rate_card)} categories)" if rate_card else " — no rate card on file yet")
        + ". Enter **hours** only; the extended column totals itself.",
        "",
        f"**4. Tailor the draft.** `01-proposal.md` has **{blanks_left} blanks** left,"
        " marked `[[FILL: ...]]`. Search for that string and work through them.",
        "",
        "**5. Send it.** `03-quote-email.txt` is addressed and written. Confirm the"
        " submission method on the listing, sign the price sheet, send.",
        "",
        "## Already done for you",
        "",
    ]
    done = [
        "Matched to your NAICS codes and scored",
        "Set-aside eligibility checked against the certifications you hold",
        "Offeror identity, UEI, CAGE, signatory and insurance filled from the fact bank",
        f"Past performance: {len(refs)} reference(s) carried in from the fact bank"
        if refs else "Past performance: none on file yet — add real contracts to company.toml",
        f"Price sheet seeded with {len(rate_card)} labor categories"
        if rate_card else "Price sheet skeleton (add a rate card to company.toml to seed it)",
        f"{len(attachments)} solicitation attachment(s) downloaded"
        if attachments else "Attachment manifest written",
        "Cover email drafted and addressed to the contracting officer",
    ]
    lines += [f"- {item}" for item in done]

    if failed:
        lines += [
            "",
            "## Get these by hand",
            "",
            f"{len(failed)} attachment(s) could not be downloaded — see"
            " `attachments/MANIFEST.txt` for the URLs.",
        ]

    lines += [
        "",
        "## Only you can do these",
        "",
        "- **The go/no-go call.** Capability is a judgment, not a keyword match.",
        "- **The price.** A price is a binding offer. Nothing here guesses one.",
        "- **The signature.** It certifies your reps & certs are true. That is a",
        "  legal act by a person with authority, and it is why this tool prepares",
        "  a submission but never sends one.",
        "",
        "---",
        f"_Packet built {date.today().isoformat()}. Draft, not a submission._",
        "",
    ]
    return "\n".join(lines)


def build_packet(opp, description_text, company, root, score=None, reasons="", session=None):
    """Writes the whole folder. Returns (path, blanks_left, status).

    Status is one of:
      new        built for the first time
      refreshed  the fact bank changed and nothing here had been edited,
                 so the packet was regenerated against the newer facts
      kept       edited by you, or already current — left alone
      partial    the fact bank changed but some files are edited; only the
                 untouched ones were refreshed

    The reason for all this: a packet built while company.toml was still
    empty carries blanks for facts you have since entered. Refusing to
    overwrite anything would freeze that emptiness in place forever, and
    overwriting everything would destroy a price sheet you spent an hour
    on. So the distinction is per file and based on content, not time.
    """
    out = packet_dir(opp, root)
    fingerprint = company_fingerprint(company)
    existing = os.path.exists(os.path.join(out, "00-START-HERE.md"))

    if existing:
        meta = _read_meta(out)
        if meta.get("company_fingerprint") == fingerprint:
            return out, meta.get("blanks_left"), "kept"
        replaceable = untouched_files(out, meta)
        if not replaceable:
            return out, meta.get("blanks_left"), "kept"
        status = "refreshed" if replaceable == set(GENERATED) else "partial"
    else:
        replaceable = set(GENERATED)
        status = "new"

    os.makedirs(out, exist_ok=True)

    draft = proposal.build_proposal_markdown(opp, description_text, company, score, reasons)
    blanks_left = len(re.findall(r"\[\[FILL:", draft))

    written = {}
    if "01-proposal.md" in replaceable:
        path = os.path.join(out, "01-proposal.md")
        with open(path, "w") as f:
            f.write(draft)
        written["01-proposal.md"] = _file_hash(path)
    if "02-price-sheet.csv" in replaceable:
        path = write_price_sheet(opp, company, os.path.join(out, "02-price-sheet.csv"))
        written["02-price-sheet.csv"] = _file_hash(path)
    if "03-quote-email.txt" in replaceable:
        path = os.path.join(out, "03-quote-email.txt")
        with open(path, "w") as f:
            f.write(build_quote_email(opp, company))
        written["03-quote-email.txt"] = _file_hash(path)

    got, failed = fetch_attachments(opp, os.path.join(out, "attachments"), session=session)

    if "00-START-HERE.md" in replaceable:
        path = os.path.join(out, "00-START-HERE.md")
        with open(path, "w") as f:
            f.write(build_start_here(opp, company, blanks_left, got, failed))
        written["00-START-HERE.md"] = _file_hash(path)

    # Files we deliberately left alone keep the hashes they had, so a later
    # rebuild still recognises them as the user's work.
    previous = (_read_meta(out).get("files") or {}) if existing else {}
    merged = {**previous, **written}
    with open(os.path.join(out, META_NAME), "w") as f:
        json.dump(
            {"company_fingerprint": fingerprint, "blanks_left": blanks_left,
             "built": date.today().isoformat(), "files": merged},
            f, indent=2,
        )
    return out, blanks_left, status


def write_batch_index(built, skipped, root, profile_label):
    """One page listing today's batch, soonest deadline first — the
    conveyor belt's output tray."""
    rows = []
    for out, opp, blanks_left, *rest in built:
        status = rest[0] if rest else ""
        deadline, days = _deadline_parts(opp)
        rows.append((days if days is not None else 9999, deadline, days, out, opp,
                     blanks_left, status))
    rows.sort(key=lambda r: r[0])

    lines = [
        f"# Bid packets — {profile_label}",
        f"_{date.today().isoformat()} — {len(built)} packet(s), soonest deadline first_",
        "",
        "| Due | Days | Title | Blanks left | State | Folder |",
        "|---|---|---|---|---|---|",
    ]
    for _, deadline, days, out, opp, blanks_left, status in rows:
        title = (opp.get("title") or "")[:70]
        folder = os.path.basename(out)
        left = "-" if blanks_left is None else str(blanks_left)
        lines.append(
            f"| {deadline} | {days if days is not None else '?'} | {title} | {left} "
            f"| {status} | `{folder}/` |"
        )

    if skipped:
        lines += [
            "",
            "## Not built",
            "",
            "| Title | Why |",
            "|---|---|",
        ]
        for opp, why in skipped:
            lines.append(f"| {(opp.get('title') or '')[:70]} | {why} |")

    lines += [
        "",
        "Work the top of the table first — those close soonest.",
        "Each folder's `00-START-HERE.md` is the five-step checklist.",
        "",
    ]
    path = os.path.join(root, "INDEX.md")
    os.makedirs(root, exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path
