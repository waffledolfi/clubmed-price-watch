# Club Med price watch

Tracks the price of specific Club Med stays and alerts you when they drop or
hit a target. Pure Python 3 standard library — no pip installs, no browser.

## How it gets prices

The clubmed.com.sg page loads prices over XHR, so there is nothing to scrape
from the HTML. Behind its GraphQL gateway sits a plain JSON endpoint:

    https://api.clubmed.com/v1/search_price
      ?product_id=KIPC_WINTER&first_date=20270330&duration=5
      &number_attendees=2&api_key=...          (Accept-Language: en-SG)

The site displays `best_price + fees_amount`, so that sum is what's tracked.
For 30 Mar – 4 Apr 2027 that is 5040 + 92 = **S$5,132**, matching the website
exactly, with `initial_price + fees` = S$6,392 as the struck-through list price.

## Budget note: add ~S$1,000 yourself

**The tracked price is the Club Med booking cost only.** On top of it, budget
about **S$1,000** for a snowboard set (4 days, 2 adults) and airport transfers.
Club Med does not charge these, so they never appear in any price this tool
reads from the API.

That figure lives in the `extras` block of `watches.json` and is shown
everywhere a price is: the `check` output, the scan table's "all-in" column,
the dashboard's "Budget all-in" tile, and inside alert messages. Change the
amount or wording there and it updates everywhere.

`target_price` is compared against the **Club Med price**, not the all-in
figure — a S$4,800 target fires when Club Med itself hits S$4,800
(~S$5,800 all-in).

## Setup

Edit `watches.json`. To add a stay, copy its URL from clubmed.com.sg and run:

    python3 watch.py resolve "https://www.clubmed.com.sg/r/kiroro-peak/w?adults=2&children=0&start_date=2027-03-30&end_date=2027-04-04"

That prints a ready-to-paste entry. Set `target_price` to the number you want
to be told about. Leave `departure_option_id` as `null` for resort-only pricing,
or set `"SIN"` to price the flight-inclusive package.

## Commands

    python3 watch.py check                     check now, record, alert, rebuild dashboard
    python3 watch.py scan KIPC_WINTER 2027-01-01 2027-04-30 7
                                               price every start date in a range
    python3 watch.py scan KIPC_WINTER 2027-01-01 2027-04-30 5,6,7
                                               ...across several stay lengths
    python3 watch.py scan KIPC_WINTER 2027-01-01 2027-04-30 5,7 7
                                               ...checking one weekday only (step 7)
    python3 watch.py history                   print everything recorded
    python3 watch.py dashboard                 rebuild dashboard.html
    python3 watch.py install 6                 run automatically every 6 hours
    python3 watch.py uninstall                 stop running automatically

## Searching other weeks

`scan` is not limited to your watched dates — it prices every start date in any
range you give it. The 4th argument is stay length and takes a comma list; the
5th steps the start date, so `7` checks the same weekday each week and keeps the
request count down.

    python3 watch.py scan KIPC_WINTER 2027-01-01 2027-04-30 5,6,7 7

Output is one row per start date with a column per stay length, then a ranked
"cheapest found" table with an all-in column. Anything at or under your
`target_price` is starred. A full season at three lengths is a few hundred
requests at ~1s apart — expect several minutes, and prefer a step of 7 for a
first pass, then a step of 1 around whichever week looks good.

## Alerts

You get a macOS notification plus a line in the log when:

* the price is at or below `target_price`, or
* the price dropped versus the previous reading.

To also push alerts to your phone, create a free topic at https://ntfy.sh and
put `https://ntfy.sh/your-topic-name` in `notify.webhook_url` in `watches.json`.

## Sharing it with someone

`publish.py` turns the recorded history plus the latest season scan into
`share.html`, a single self-contained page: the watched week with its target,
every scanned week ranked and graded, and an all-in toggle that adds the
extras to every figure at once.

    python3 watch.py check                     refresh the watched week
    python3 watch.py scan KIPC_WINTER 2026-12-01 2027-04-27 4,5,6 7
                                               refresh the season sweep
    python3 publish.py                         rebuild share.html

`share.html` is hosted as a Claude Artifact, which is private until you share
it from the page's own share menu.

Live link: https://claude.ai/code/artifact/44069fcd-7bba-43fc-bd34-2484b98a7c28

It is a **snapshot**, not a live feed. A published Artifact is blocked from
calling any external host, so the page cannot fetch Club Med prices itself and
no button on it could ever do so. Refreshing has to be driven from outside the
page. Two scheduled tasks do that (Claude app sidebar, "Scheduled"):

* **kiroro-price-refresh** — runs every 2 days at 07:23, re-reads every price
  and republishes the page to the same link.
* **kiroro-price-refresh-now** — the same job with no schedule, for on demand.

Both only run while the Claude app is open; a run missed while it was closed
happens at next launch. Neither ever republishes on failure, so a Club Med API
change leaves the last good page up rather than replacing it with an empty one.

### Pre-approving the automatic job

Tool approvals are stored **per task**, so approving one routine does not
approve the other. Running `kiroro-price-refresh-now` banks permissions for
that task only — the every-2-days `kiroro-price-refresh` is separate.

Because nobody is watching when the automatic job fires at 07:23, run
**`kiroro-price-refresh`** manually once from the Routine tab and approve its
prompts. That both banks its permissions and performs a real refresh.

`kiroro-price-refresh-now` does not need pre-approving: you are at the keyboard
whenever you start it, so answering its prompt on first use costs nothing.

### Refreshing on demand

The routines are in the Claude desktop app under the **Routine** tab (not a
"Scheduled" sidebar).

1. Open the **Routine** tab.
2. Pick **kiroro-price-refresh-now**.
3. Start it. The first time, approve the tool permissions it asks for.
4. Wait 3&ndash;4 minutes. It re-checks the watched week, re-scans the season
   (~66 API calls, deliberately paced 1s apart), rebuilds the page and
   republishes it to the same link.
5. It finishes by reporting the tracked week's price, whether the target is
   hit, and the three cheapest stays.

Reload the shared link and check the "snapshot taken" stamp at the top to
confirm it went through.

Two alternatives that skip the Routine tab:

* Run `./refresh.sh` in this folder, then ask Claude in any session to
  "republish the Kiroro price watch page". The script updates local data;
  only Claude can republish the artifact.
* Just ask Claude to "refresh and republish the Kiroro price watch" — it does
  the whole thing.

## Hosting on GitHub Pages

`publish.py` writes two files from the same template:

* `share.html` — a fragment, for publishing as a Claude Artifact
* `docs/index.html` — a complete page, for GitHub Pages

Pages serves `docs/` on the `main` branch. `.github/workflows/refresh.yml` runs
the whole refresh **in GitHub's cloud** every 2 days (23:23 UTC = 07:23 SGT),
commits the rebuilt page, and Pages redeploys it. Nothing local is involved —
this Mac can be shut, and the Claude app closed.

The workflow also has `workflow_dispatch`, so the repo's **Actions → Refresh
Kiroro prices → Run workflow** button is a real on-demand refresh from any
browser, including a phone.

`publish.py` refuses to rebuild the page from fewer than 10 season quotes, so
if Club Med changes their API the job fails loudly and the last good page stays
up. Override deliberately with `ALLOW_SPARSE=1`.

### One-time setup

**1. Create the repo.** On github.com: **+** (top right) → **New repository**.

* Name: `clubmed-price-watch` (or anything)
* Visibility: **Public** — this is what makes Pages and Actions free
* Leave "Add a README", ".gitignore" and "licence" **unticked** — this folder
  already has them, and adding them causes a push conflict
* **Create repository**

**2. Push.** From this folder:

    git remote add origin https://github.com/waffledolfi/clubmed-price-watch.git
    git push -u origin main

Git will ask for a username and password. **The password is not your GitHub
password** — GitHub stopped accepting those. It must be a Personal Access Token:

* github.com → your avatar → **Settings** → **Developer settings** (very bottom
  of the left menu) → **Personal access tokens** → **Tokens (classic)** →
  **Generate new token (classic)**
* Note: `clubmed-price-watch`, Expiration: your choice
* Tick the **`repo`** scope (that alone is enough)
* **Generate token**, copy it — it is shown once
* Paste it as the *password* at the git prompt; the username is `waffledolfi`

macOS stores it in the keychain, so you are asked only once.

**3. Turn on Pages.** Repo → **Settings** → **Pages** (left menu)

* Source: **Deploy from a branch**
* Branch: **main**, Folder: **/docs**
* **Save**

**4. Let the workflow commit.** Repo → **Settings** → **Actions** → **General**
→ scroll to **Workflow permissions** → **Read and write permissions** → **Save**.

Without this the job runs, fetches prices, then fails on the final push. This is
the step most people miss.

**5. Test it.** Repo → **Actions** tab → **Refresh Kiroro prices** (left) →
**Run workflow** → **Run workflow**. It takes about 4 minutes.

Your page is then at:

    https://waffledolfi.github.io/clubmed-price-watch/

Pages can take a few minutes to serve the first time.

### If something goes wrong

| Symptom | Cause |
|---|---|
| Push rejected, `403` or `Authentication failed` | Token missing the `repo` scope, or you typed your account password instead of the token |
| Push rejected, `fetch first` / `non-fast-forward` | You ticked "Add a README" when creating the repo. `git pull --rebase origin main` then push again |
| Actions job red on the last step | Workflow permissions still read-only — step 4 |
| Page 404s | Pages folder not set to `/docs`, or give it a few minutes |
| Job fails with "Only N season quotes" | The safety guard fired. Club Med's API may have changed, or blocked the datacenter IP. The previously published page stays up |
| Prices in the wrong currency | The runner's locale differs. The `Accept-Language: en-SG` header is set in `clubmed.py`; check it is still being sent |

## Scheduling notes

`install` uses launchd, which only runs while this Mac is awake — a laptop
asleep for two days checks nothing in that window. For genuinely unattended
monitoring the same script needs to run somewhere always-on.

Checks are deliberately infrequent (every 6 hours by default) and `scan` sleeps
1s between dates. Please keep it that way — this is a personal watcher hitting
an endpoint your browser already calls, and it should stay indistinguishable
from ordinary use.

## Files

    clubmed.py       API client
    watch.py         CLI, storage, alerts, dashboard
    watches.json     what to watch
    prices.db        SQLite history (created on first run)
    dashboard.html   generated chart + table (local, private)
    publish.py       builds the shareable page
    share_template.html  its markup and styling
    share.html       generated shareable page
    scan_*.json      saved season sweep
    watch.log        launchd output
    refresh.sh       one-command local refresh
