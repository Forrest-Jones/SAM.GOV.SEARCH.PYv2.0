# SAM.GOV.SEARCH.PYv2.0

Finds, ranks, and triages SAM.gov contract opportunities against Proverbs
1821 Consulting LLC's NAICS codes (tax center support, accounting/tax
remediation, and third-party program evaluation). New high-scoring
opportunities get a markdown review scaffold and, if configured, an
email digest.

**This tool never submits a bid.** SAM.gov has no API for bid
submission — federal proposal responses are a signed, human process
(technical narrative, priced proposal, reps/certs) submitted by email or
an agency portal. Automating that step isn't just infeasible, it's a
bad idea: a bid submitted with a wrong price, a boilerplate response
that doesn't answer the PWS, or a certification you don't actually hold
is a compliance problem (False Claims Act exposure, suspension/debarment
risk), not a bug to patch later. This tool gets you from "here's what's
out there" to "here's a scaffold ready for your review" — you decide
go/no-go and you submit.

## Setup

```bash
pip install -r requirements.txt
export SAM_API_KEY="your-key-here"
```

Get a free API key at sam.gov -> Account Details -> Get API Key (1,000
calls/day). **If a key has ever been pasted into a chat or committed to
git, rotate it before using it here.**

Optional, for the email digest:

```bash
export GMAIL_USER="youraddress@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
```

Gmail App Passwords: Google Account -> Security -> 2-Step Verification ->
App passwords. Requires 2FA enabled on the account. Never use your
regular Gmail password here.

## Usage

```bash
python3 find_opportunities.py
```

Prints a ranked shortlist to the terminal. Notices seen for the first
time (tracked in `state.sqlite3`) that score at or above
`--draft-min-score` (default 4) get a markdown scaffold in `drafts/`
with the full description, attachment links, and a go/no-go checklist.
If `GMAIL_USER`/`GMAIL_APP_PASSWORD` are set and there's at least one new
notice, a digest email goes out.

Common flags:

```bash
# Override NAICS codes
python3 find_opportunities.py --naics 541213,541990

# Also write the full ranked list to CSV
python3 find_opportunities.py --csv results.csv

# Include set-asides you're not certified for (8(a), HUBZone, SDVOSB, etc.)
python3 find_opportunities.py --include-restricted-set-asides

# Skip draft generation / email for a quick manual check
python3 find_opportunities.py --no-drafts --no-email
```

See `python3 find_opportunities.py --help` for the full option list
(posted-days window, deadline window, retry count, custom db/drafts
paths, digest recipient).

## Eligibility filtering

Set-aside notices are classified three ways:

- **eligible_set_aside** — total small business, WOSB, or EDWOSB
  set-asides. Scored with a bonus.
- **unknown_set_aside** — some other set-aside type the script doesn't
  recognize. Shown, but flagged "verify eligibility" instead of scored
  up, so it doesn't get buried or falsely boosted.
- **restricted** — 8(a), HUBZone, SDVOSB, or VOSB set-asides. Excluded
  from output by default since we don't hold those certifications; pass
  `--include-restricted-set-asides` to see them anyway.

Update `ELIGIBLE_SET_ASIDE_HINTS` / `RESTRICTED_SET_ASIDE_HINTS` in
`find_opportunities.py` if your certifications change.

## Scheduling (GitHub Actions)

`.github/workflows/daily-search.yml` runs the search daily at 12:00 UTC
(and on-demand via workflow_dispatch), then commits the updated
`state.sqlite3` and any new `drafts/*.md` back to the repo — so drafts
are reviewable right here on GitHub, and the "new since last run" diff
persists across runs.

Add these as repository secrets (Settings -> Secrets and variables ->
Actions):

| Secret | Required | Purpose |
|---|---|---|
| `SAM_API_KEY` | yes | SAM.gov API access |
| `GMAIL_USER` | optional | From-address for the digest |
| `GMAIL_APP_PASSWORD` | optional | Gmail App Password for that address |

Without the Gmail secrets, the workflow still runs and still commits
drafts — you just won't get an email and will need to check the repo
(or `drafts/`) directly.

## Tests

```bash
pip install pytest
pytest
```

Runs automatically on every push via `.github/workflows/test.yml`.

## What this doesn't do (by design)

- Submit bids, proposals, or any response to a contracting officer
- Auto-decide go/no-go — that's a human capture decision
- Guarantee eligibility — the eligibility classifier is a heuristic on
  notice text, not a legal determination; confirm size standard and
  certification status yourself before treating anything as biddable
- Cover Ares Robotics' separate NAICS set (562998, 562910, 562211,
  811310, 333998 / PSC F108, J039) — say the word for a `--profile` flag
  or a second script if that's needed later
