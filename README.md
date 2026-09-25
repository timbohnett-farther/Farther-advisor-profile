# Farther Advisor Roster

This is every active Farther advisor, pulled nightly from the Sanity CMS behind farther.com. The same data powers the public advisor profile pages. This repo keeps a clean copy that Claude Projects, Claude Design, and people can use.

## What's in `data/`

| File | Use it for |
|---|---|
| `advisors.json` | Full roster. This is the file Claude should read. |
| `advisors.csv` | The same data as a flat table. Opens cleanly in Excel. |

Both files are rewritten only when the roster actually changes. That means the commit history also works as a change log: each commit message lists who was added, who was removed, and whose details changed.

## Field guide

| Field | What it is | Notes |
|---|---|---|
| `displayName` | Name without designations, e.g. "Alan Gappinger" | Use this in headlines, greetings, and cards. Keeps Jr./Sr. |
| `designations` | Letters after the name, e.g. `["CLU®", "ChFC®", "CFP®"]` | Taken from the published name, marks included. Can also include degrees like MBA, JD, PhD. |
| `nameAsPublished` | Name exactly as it appears on farther.com | Use this when the full formal name is needed. |
| `title` | Job title | Blank for a couple of advisors. |
| `email` | Farther email | Blank for about 1 in 10. |
| `phone` | Phone in one standard format, e.g. `+16025551234` | Blank for about 4 in 10. Sanity stores ten different formats; this is cleaned up. |
| `phoneExt` | Extension, if any | Rare. |
| `phoneDisplay` | Phone formatted for print, e.g. "(602) 555-1234" | Use this in anything a person will read. |
| `city`, `state` | Office location | A few are blank. |
| `team` | `name`, `url`, `logoUrl` of the advisor's team, or blank | About a third of advisors belong to a team. Some teams have no logo. |
| `profileUrl` | Public profile page on farther.com | |
| `headshotUrl` | Original photo file | Most are AVIF, which PowerPoint, Word and many older tools can't open. |
| `headshotJpgUrl` | Same photo as a full-size JPG | Use for print or anything going into Office files. |
| `headshotSquareUrl` | 600 x 600 JPG, cropped square | Use for cards, grids, and social graphics. |
| `credentials` | Education, licenses, and affiliations as listed on the profile | Free text, e.g. "BA, University of Miami" or "Series 65". Not a clean designation list; use `designations` for that. |
| `slug` | The advisor's unique ID (end of the profile link) | Stays the same even if a name changes. |

### Headshot sizes

Headshots are served by Sanity, which resizes and converts them on request. You can build any size by changing the numbers after the original `headshotUrl`:

```
<headshotUrl>?w=1200&h=1200&fit=crop&fm=jpg&q=90    large square
<headshotUrl>?w=300&fm=jpg                           small, original shape
```

`fm=jpg` converts to JPG. `fit=crop` crops to the exact width and height.

## How the nightly refresh works

`.github/workflows/refresh-advisors.yml` runs every night at 2:00 AM Phoenix time. It:

1. Runs `scripts/refresh_advisors.py`, which sends the query in `scripts/advisors.groq` to Sanity.
2. Cleans the results (names, phones, headshot links) and compares them to what's already saved.
3. Commits and pushes new files only if something changed.

No passwords or keys are needed. The data is already public on farther.com.

### Safety check

If Sanity returns nothing, or the roster shrinks by more than 15% since the last save, the run stops and saves nothing. GitHub emails whoever set up the workflow when a run fails. That protects the roster from being wiped by a website outage.

If a big drop is real (say a team departs), go to **Actions > Refresh advisor roster > Run workflow**, check **force**, and run it.

### Run it by hand

**Actions** tab > **Refresh advisor roster** > **Run workflow** > **Run workflow**. Takes about 20 seconds.

To run it on your own computer (optional, needs Python 3):

```
python3 scripts/refresh_advisors.py        # Mac
py scripts\refresh_advisors.py             # Windows
```

### Change what gets pulled

Edit `scripts/advisors.groq`. It's the same query as the original long link, laid out on separate lines so it's easier to read. After editing, run the workflow by hand to check it.

## Using this in Claude

**Claude Projects:** In the project, go to Project knowledge > **+** > **GitHub**, pick this repo, and select `data/advisors.json` and `README.md`. Projects don't pull changes automatically, so click **Sync now** when you want the latest roster.

**Claude Design:** Open a design project, choose **Import > GitHub**, and link this repo the same way.

## Troubleshooting

| Problem | Fix |
|---|---|
| Run fails on `git push` with a 403 or "permission denied" | Settings > Actions > General > Workflow permissions > choose **Read and write permissions**. If it's grayed out, a GitHub org owner has to allow it at the org level. |
| Push is rejected because `main` is protected | Add an exception for GitHub Actions in the branch rule, or ask the org owner to. |
| Nightly run never shows up in Actions | The schedule only runs from the default branch (`main`), and the workflow file has to be at exactly `.github/workflows/refresh-advisors.yml`. |
| Run fails with "Could not pull the roster from Sanity" | Usually a brief outage. The script already retries three times. It will try again the next night. |
