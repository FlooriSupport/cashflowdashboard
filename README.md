# Floori.io — Stripe Revenue Dashboard

Auto-updated every weekday at **9:30 AM BRT** via GitHub Actions → published on GitHub Pages.

---

## Setup (one time, ~10 minutes)

### 1. Create a GitHub repository

1. Go to [github.com/new](https://github.com/new)
2. Name it `floori-dashboard` (or anything you like)
3. Set to **Private**
4. Click **Create repository**

### 2. Upload the files

Upload these files to the root of the repository:
- `index.html` ← the dashboard
- `update_dashboard.py` ← the update script
- `.github/workflows/update.yml` ← the automation schedule

You can do this via the GitHub web UI (drag & drop) or with `git`.

### 3. Add your Stripe API key as a secret

1. In your repo, go to **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `STRIPE_API_KEY`
4. Value: your Stripe **Restricted Key** (read-only access to Customers and Subscriptions)
5. Click **Add secret**

> To create a restricted key in Stripe: Dashboard → Developers → API keys → Create restricted key → enable read access for Customers and Subscriptions only.

### 4. Enable GitHub Pages

1. Go to **Settings → Pages**
2. Under "Source", select **Deploy from a branch**
3. Branch: `main` / folder: `/ (root)`
4. Click **Save**

After a minute, your dashboard will be live at:
`https://YOUR-USERNAME.github.io/floori-dashboard/`

### 5. Run it manually the first time

1. Go to **Actions → Update dashboard**
2. Click **Run workflow**
3. Wait ~30 seconds — the dashboard will update and deploy

---

## How it works

```
Every weekday 9:30 AM BRT
        │
        ▼
GitHub Actions wakes up
        │
        ▼
update_dashboard.py runs
  → Fetches all subscriptions from Stripe API
  → Maps customer IDs to names
  → Regenerates index.html with fresh data + timestamp
        │
        ▼
Git commits & pushes index.html
        │
        ▼
GitHub Pages auto-deploys
  → Your URL is live with updated data
```

---

## Updating monthly projections

The file `update_dashboard.py` contains a `MONTHLY_PROJECTIONS` dictionary with the
May–Dec 2026 revenue schedule per customer (based on the Floori cashflow CSV).

To update projections for a new period, edit that dictionary and push the change.
The next scheduled run will pick it up automatically.

---

## Manual trigger

To force an update at any time:
**Actions → Update dashboard → Run workflow**
