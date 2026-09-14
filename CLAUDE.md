# Proverbs 1821 Consulting LLC — standing facts

Read this before working on any opportunity. It is the authoritative record
of who the firm is, who performs the work, and what may and may not be
claimed on a federal submission.

## The entity

One entity bids: **Proverbs 1821 Consulting LLC**, a Texas single-member
LLC formed 12 February 2026.

| | |
|---|---|
| UEI | GD83PAK36818 |
| CAGE | 22ND2 |
| SAM | Active, renews 2027-07-07 |
| Address | 12103 Hawthorne Dr, Montgomery, TX 77356 |
| Signatory | Forrest Andrew Jones, Owner / Managing Member |
| Phone | (832) 562-1355 · alt (832) 662-1812 |
| Email | forrestjones2010@gmail.com |
| Size | Small business |

**Ares Robotics is in-house to Proverbs 1821.** Do not ask for a separate
Ares UEI, CAGE or registration, and do not treat Ares as a customer or a
subcontractor needing its own identity. Both search profiles bid under the
Proverbs 1821 registration above. The `ares` profile is a work-type lane,
not a separate company.

## Who performs the work

| Person | Brings |
|---|---|
| **Forrest A. Jones** — Principal | 25 years capital markets and corporate finance; Certified Healthcare Financial Professional (CHFP); active IRS PTIN; software engineering training. Also Chief Investment Officer of Blackwater Investment Group, Inc. |
| **Richard Starr** — Ares Robotics | Robotics since 1985, beginning with Navy SEAL mine search and disposal; founded Ares 1998 after six years of development. Designer of the ROV and Manway Cannon platforms. |
| **Randy White** | Enrolled Agent (IRS, Circular 230). Unlimited representation rights before the IRS. **Not a CPA** — see the prohibition below. |
| **Jason Teal** | [[FILL: role and what he brings]] |

## Certifications actually held

- Small business (self-certified in SAM against the size standard)
- Enrolled Agent — Randy White
- CHFP and active PTIN — Forrest A. Jones

## Certifications NOT held — never claim these

- **No CPA licence.** No licensed CPA in house and none engaged. An
  Enrolled Agent does not satisfy a CPA requirement: audits, attest work
  and any opinion on financial statements are reserved to CPAs licensed by
  a state board. Notices requiring a CPA are unwinnable and must not reach
  the digest as matches.
- **No WOSB or EDWOSB.** The firm is male-owned as of September 2026. An
  ownership transition to a woman owner (wife or daughter) is planned but
  not executed, and WOSB is not self-certifiable — FAR 19.15 requires SBA
  certification in place at the time a quote is submitted. Add `wosb` to
  DEFAULT_HELD_CERTS only when SBA has issued it.
- **No facility clearance and no cleared personnel.** Blocks performance
  of cleared work; does not block responding to a Sources Sought.
- **No 8(a).**
- **No EPA/RCRA permits, DOT hazmat certification or TSDF agreements** held
  by the firm itself. Ares' industrial capability is real, but permitted
  waste transport and disposal authority is a separate question — confirm
  before claiming it.

## Capability that is genuinely ours

**Financial and administrative support** — budget formulation and
execution tracking, variance and burn-rate analysis, reconciliation,
funding-document control, recurring management reporting, decision-support
materials, and the executive and administrative staff work around it:
document control, records management, correspondence, meeting support,
action tracking. Principal-led; specialists contracted by name under
written agreement rather than junior labor billed at senior rates.
Reporting infrastructure is built rather than hand-assembled — API
integrations, recurring report generation, pipeline and exception
monitoring.

**Industrial robotics and vessel services, via Ares in-house** — over 33
models of Remotely Operated Vehicle across four core chassis, Generation 6,
assembled per job to match material, viscosity and manway size. Wheeled
traction rather than tracks; proprietary spiral propeller compression hood
technology; vehicles 630–1600 lbs, averaging 1000 lbs and 120 HP.
Self-contained launch carts requiring no plant lifting aid. Class 1 Div 1
camera and lighting systems including low-light, infrared and FLIR thermal.
Manway Cannon Systems — the only system with hydraulic nozzles, a
split-manway design, and the ability to degas while removing material.
Centrifuge manufacturing, repair, rental and sales with an in-house machine
shop. In-service top-entry vessel inspection with simultaneous SLOFEC NDT
for API 653 profiling, performed while the tank remains in service.

Deployed by Exxon, Shell, Conoco, Chevron, Marathon, DuPont, Valero, BP,
TransCanada, Enbridge, Suncor and Oil Sands operators.

**Program evaluation, via affiliation** — Blackwater Evaluation, operated
by Blackwater Investment Group, Inc., a third-party program evaluation
practice serving federal research sponsors. Forrest A. Jones is its Chief
Investment Officer.

## How to cite all of that on a federal submission

Use it fully, and label it accurately. The distinction is not caution, it
is what survives a contracting officer checking:

- **Personnel experience is ours to claim.** Richard Starr's robotics
  record, Randy White's EA practice, Forrest Jones' finance career — these
  are the experience of people who perform the work, and belong in a key
  personnel section without qualification.
- **In-house capability is ours to claim.** The ROV fleet, the Manway
  Cannons, the machine shop, the inspection system. Describe them as
  resources the firm brings, because they are.
- **Corporate contract history stays attributed.** Write "Ares Robotics,
  in-house to Proverbs 1821, has deployed these systems for Exxon, Shell
  and Chevron" — not "Proverbs 1821 performed an Exxon contract." Same
  facts, same weight to an evaluator, and it does not misstate which legal
  entity held a contract. Blackwater is an affiliation and a teaming
  resource, cited as such.
- **Proverbs 1821 itself has no federal past performance.** Say so plainly
  where past performance is asked for. `past_performance_note` in
  company.toml carries the standing language.

## Things already decided — do not revisit

- Solicitation **47QACA26R0306** (GSA Risk Management) is not being
  pursued. Never raise it again.
- Never attempt automated bid submission. Federal offers carry signed
  representations and certifications; the tool prepares, a person sends.
- Never write a price, a rate or an hour figure the owner did not give.
- Never paste an API key or password into chat or a file. The SAM key lives
  in gitignored `.env.local` locally and in GitHub Secrets for CI.

## Where this work lives

This repository is the only home for the SAM.gov opportunity pipeline, and
it is the shared state between sessions — everything is committed and
pushed, nothing is local-only. On the owner's Mac the clone is at
`~/SAM.GOV.SEARCH.PYv2.0`; `bash start.command` runs the web app.

There is an unrelated HighLevel CRM project at `~/bwig-ghl` on that
machine. It has no SAM.gov context and is not part of this work. A session
opened there looked in `~/samgov` — an empty folder — and concluded the
app did not exist. It does; that was the wrong directory. Do not treat
that project as a source for anything here, and do not split this work
across it.

## Open items

- Facts still blank in `company.toml` that every packet asks for:
  `accounting_system`, the four `secondary_contact_*` keys, `rate_card`
  rows (labor category + rate — no priced bid can be finished without
  them), and `insurance_*` / `workers_comp`.
- Add **NAICS 541219** and **PSC R499** to the SAM registration. Notices
  require small-business status under the assigned NAICS to prime, and the
  registration currently carries neither.
- Jason Teal's role is unrecorded.
- Confirm or strike the dollar values and periods in
  `p1821.past_performance` — every one is currently a placeholder.
