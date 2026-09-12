# Deploying Contract Finder as a real website

This turns the local web UI into a URL you can open from any device. You
create the hosting account (only you can accept a host's terms of
service); the config files in this repo do the rest.

**Pick one host.** Deploying to all three costs three times the setup and
gives you three URLs to keep track of. The comparison below is the whole
decision.

| | Render | Railway | Fly.io |
|---|---|---|---|
| Free tier | Yes, sleeps when idle | Trial credit, then paid | Yes, small VMs |
| Keeps your data between deploys | **No** (paid disk only) | Yes (volume) | Yes (volume) |
| Setup | Connect repo, done | Connect repo, done | Install `flyctl`, run 3 commands |
| Best if | You just want it up fastest | You want persistence without a CLI | You want persistence on a free tier |

"Keeps your data" matters more than it sounds: without a persistent
volume, every redeploy wipes `state.sqlite3` (which notices you've
already seen), your `drafts/` review packets, and your saved settings.
The app still works — but it will re-flag old contracts as "NEW" and
you'll lose checklist progress. **Fly.io is the best free option** for
that reason.

## Required environment variables

Set these in the host's dashboard (or via `fly secrets set`). Never
commit them.

| Variable | Required | What it is |
|---|---|---|
| `APP_PASSWORD` | **Yes** | The password to open the site. Without it a public deploy refuses to serve at all — see "Why a password" below. |
| `SAM_API_KEY` | **Yes** | Your SAM.gov API key. |
| `PUBLIC_DEPLOY` | Yes (set to `1`) | Marks this as internet-facing. Already set in each config file. |
| `DATA_DIR` | Yes | Where writable state goes; must be your mounted volume path. Already set in each config file. |
| `GMAIL_USER` | Optional | From-address for email digests. |
| `GMAIL_APP_PASSWORD` | Optional | Gmail **App Password**, not your Google password. |

Pick a long random `APP_PASSWORD` — a password manager's generator is
ideal. Don't reuse a password you use elsewhere, and don't paste it into
a chat or an issue.

## Why a password

A deployed copy is reachable by anyone who finds the URL, and it holds a
live SAM.gov API key plus your whole bid pipeline. Without a gate, a
stranger could read what you're bidding on, change your search settings,
and burn your 1,000-calls-per-day API quota. So the app enforces this: if
`PUBLIC_DEPLOY=1` and `APP_PASSWORD` is unset, it returns an error on
every page instead of serving. Your browser will prompt for the password
once and remember it for the session (any username works — only the
password is checked).

This is a single shared password, which is right for one business using
one tool. It is not a multi-user login system; don't hand the URL and
password to people you wouldn't give the API key to.

## Render

1. Push this repo to GitHub (already done).
2. render.com → **New** → **Blueprint** → pick this repo. It reads
   `render.yaml`.
3. When prompted, fill in `APP_PASSWORD` and `SAM_API_KEY` (and the Gmail
   pair if you want digests).
4. Deploy. Your URL appears in the dashboard.

Free instances sleep after inactivity, so the first load after a while
takes ~30 seconds to wake. Free instances also have **no persistent
disk** — to keep your data, upgrade the instance and uncomment the `disk:`
block at the bottom of `render.yaml`.

## Railway

1. railway.app → **New Project** → **Deploy from GitHub repo** → this repo.
   It reads `railway.json`.
2. **Variables** tab → add `APP_PASSWORD` and `SAM_API_KEY`.
3. **Settings** → **Volumes** → add a volume mounted at `/data`, then set
   the variable `DATA_DIR=/data`.
4. **Settings** → **Networking** → **Generate Domain** to get your URL.

## Fly.io

Needs the `flyctl` CLI once: `brew install flyctl` (macOS).

```bash
fly auth signup          # or: fly auth login
fly launch --no-deploy   # claims an app name; keep the existing fly.toml
fly volumes create contract_finder_data --size 1 --region dfw
fly secrets set APP_PASSWORD='<a long random password>' SAM_API_KEY='<your key>'
fly deploy
fly open
```

Optional email digests: `fly secrets set GMAIL_USER='you@gmail.com' GMAIL_APP_PASSWORD='xxxx xxxx xxxx xxxx'`

`fly.toml` already sets `DATA_DIR=/data` and mounts the volume there, and
`auto_stop_machines` lets the VM idle down to stay inside the free
allowance.

## After deploying

1. Open the URL, enter your `APP_PASSWORD`.
2. The Setup screen will not appear if you set `SAM_API_KEY` as an
   environment variable — it's already connected. Go straight to Home and
   hit **Find New Contracts**.
3. Check **Settings** and confirm your NAICS codes and certifications.

## Scheduled searches

The deployed web app only searches when you click the button. For a daily
automatic search with an email digest, the existing GitHub Actions
workflow (`.github/workflows/daily-search.yml`) already does that and is
independent of any deployment — add `SAM_API_KEY`, `GMAIL_USER`, and
`GMAIL_APP_PASSWORD` as repository secrets to turn it on.

## Local use is still there

None of this replaces running it locally, which needs no account, no
password, and no deploy:

```bash
python3 webapp/app.py     # then open the printed http://localhost:8000
```
