# 🌙 ToS Night Shift

**They change the rules while you sleep. We don't sleep.**

Every night, ToS Night Shift reads the Terms of Service and Privacy Policies of the apps everyone uses. When a company quietly edits a single word, it catches it, explains it in plain English, scores how much side-eye it deserves, and publishes the receipts.

No accounts. No servers. No cost. It runs on GitHub Actions and publishes to GitHub Pages.

---

## What you get

- **A public feed** of every change, newest first, filterable by topic: AI training, data sharing, arbitration, rights to your content, tracking, biometrics, kids.
- **A side-eye score (0–5)** on every change. 0 = typo fix. 5 = screenshot this.
- **The receipts.** Word-by-word diffs: red is what they deleted, green is what they snuck in.
- **Plain-English summaries** written by Claude, or by a built-in keyword radar if you don't have an API key.
- **Full history in git.** Every version of every policy is a commit. Nobody can say "we never wrote that."
- **RSS feed** and a **JSON API** (`/api/changes.json`) so anyone can build on the data.

## How it works

```
every night (GitHub Actions)
  └─ fetch each policy page          (plain HTTP, or a headless browser for JS-heavy sites)
     └─ extract just the legal text  (no menus, no cookie banners)
        └─ compare with last night's copy in snapshots/
           ├─ same            → nothing happens
           ├─ blocked/broken  → ignored, last good copy kept (no fake "they deleted everything!")
           └─ changed         → AI summary + side-eye score + receipts
                                → saved to data/changes/, site rebuilt in docs/, committed
```

**Credibility rules, enforced in code:**
- The AI only sees the diff and is told not to guess. Its quoted "receipt" is checked word for word against the real diff. If it doesn't match, it's thrown out and replaced with a real sentence.
- Pages that suddenly shrink, show a captcha or say "access denied" are never reported as changes.
- Every change page links to the original policy and to the full git history of that document.

## Launch your own in 10 minutes

1. **Create the repo.** Push this folder to a new public GitHub repository (e.g. `tos-night-shift`).
2. **Add your AI key (optional but recommended).** Repo → *Settings → Secrets and variables → Actions → New repository secret* → name `ANTHROPIC_API_KEY`. Without it you still get keyword-radar summaries.
3. **Turn on Pages.** *Settings → Pages* → Source: *Deploy from a branch* → Branch `main`, folder `/docs`.
4. **Fill in `site:`** at the top of `services.yaml` with your Pages URL and repo URL. This makes share links and "full history" buttons work.
5. **Start the first shift.** *Actions → Night shift → Run workflow.* The first run saves a baseline copy of every policy. From the next night on, every change shows up on your site.

Check the **Watching** page after the first run. Any policy marked *can't reach* or *blocked us* needs a fix in `services.yaml` (usually `render: true` or a `selector`).

## Run it on your own computer

```bash
pip install -r requirements.txt
python -m playwright install chromium      # only needed for render: true sites

python -m nightshift run --only google     # check one service
python -m nightshift run                   # check everything + rebuild the site
python -m nightshift check https://discord.com/terms   # preview the extracted text of any page
python -m nightshift build                 # rebuild docs/ from saved data
python -m pytest -q                        # tests (uses a fictional app, no network)
python -m nightshift demo                  # demo site with 3 fictional apps → demo-site/docs/index.html
```

Open `docs/index.html` in your browser to see the site.

## Add an app

One block in `services.yaml`:

```yaml
  - id: bereal
    name: BeReal
    documents:
      - { type: terms, url: "https://bereal.com/en/terms" }
      - { type: privacy, url: "https://bereal.com/en/privacy", render: true }
```

Then `python -m nightshift check <url>` to make sure the extracted text looks like the policy and not a menu. If it grabs junk, add `selector: "main"` (or whatever wraps the policy text).

Pull requests adding apps are the easiest way to contribute.

## Side-eye scale

| Score | Meaning |
|---|---|
| 0 | Nothing real changed |
| 1 | Housekeeping: dates, typos, formatting |
| 2 | Worth knowing |
| 3 | You'd want to be told |
| 4 | Most people would object |
| 5 | Screenshot this |

## Settings

| Where | Name | What it does |
|---|---|---|
| Actions secret | `ANTHROPIC_API_KEY` | Turns on AI summaries |
| Actions variable | `NIGHTSHIFT_MODEL` | Which Claude model writes summaries (default `claude-sonnet-5-5`) |
| `services.yaml` | `site.url`, `site.repo` | Share links, RSS links, history buttons |

## Part of the side-eye suite

ToS Night Shift is tool #1. Coming next, same spirit: making hidden behavior visible.

- **Ghost Job Tracker** — job ads that have been "urgently hiring" for six months
- **What Did That App Just Say** — what your apps send, and to whom, in plain sentences
- **Payslip Checker** — does your payslip match your collective agreement?

## Fine print

This project archives publicly available documents and points out changes. It is not legal advice. Summaries are generated automatically; the diff is always the source of truth.

MIT licensed.
