"""
update_dashboard.py
Fetches live subscription data from Stripe and regenerates index.html.
Runs via GitHub Actions every weekday at 9:30 AM BRT.
All data comes directly from Stripe — no CSV dependencies.
"""

import os, json, stripe, calendar
from datetime import datetime, timezone

stripe.api_key = os.environ["STRIPE_API_KEY"]

# ── Period definition: Jan–Dec 2026 ─────────────────────────────────────────
PERIOD_MONTHS = [
    datetime(2026, m, 1, tzinfo=timezone.utc)
    for m in range(1, 13)
]
PERIOD_START = PERIOD_MONTHS[0]   # Jan 1 2026
PERIOD_END   = datetime(2027, 1, 1, tzinfo=timezone.utc)


def _month_index(dt):
    """Return 0–11 for Jan–Dec 2026, or -1 if outside range."""
    if dt < PERIOD_START or dt >= PERIOD_END:
        return -1
    return dt.month - 1  # Jan=0 … Dec=11


def _add_months(dt, n):
    """Add n months to a datetime, clamping to end of month."""
    m = dt.month - 1 + n
    year = dt.year + m // 12
    month = m % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def stripe_status_to_label(status):
    return {
        "active":             "Active",
        "past_due":           "Past due",
        "unpaid":             "Unpaid",
        "canceled":           "Cancelled",
        "trialing":           "Active",
        "incomplete":         "Unpaid",
        "incomplete_expired": "Cancelled",
        "paused":             "Cancelled",
    }.get(status, "Active")


def fetch_all_subscriptions():
    subs = []
    params = {"limit": 100, "status": "all", "expand": ["data.customer"]}
    while True:
        page = stripe.Subscription.list(**params)
        subs.extend(page.data)
        if not page.has_more:
            break
        params["starting_after"] = page.data[-1].id
    return subs


def _compute_projections(sub_dict, amount_usd, interval):
    """
    Returns list of 8 floats (May–Dec 2026).
    Monthly subs: projected for each month their billing date falls in window.
    Annual subs:  projected for the renewal month within the window.
                  Checks both current_period_start (already billed this year)
                  and current_period_end (next renewal), whichever is in window.
    """
    proj = [0.0] * 12
    if amount_usd <= 0:
        return proj

    items = sub_dict.get("items", {}).get("data", [])
    ts_end   = None
    ts_start = None
    if items:
        ts_end   = items[0].get("current_period_end")
        ts_start = items[0].get("current_period_start")
    if not ts_end:
        ts_end = sub_dict.get("billing_cycle_anchor")

    if interval == "Annual":
        # Try current_period_start first (sub was already billed within our window)
        placed = False
        if ts_start:
            dt_start = datetime.fromtimestamp(int(ts_start), tz=timezone.utc)
            mi = _month_index(dt_start)
            if 0 <= mi <= 11:
                proj[mi] = round(amount_usd, 2)
                placed = True
        # Fallback: next renewal (current_period_end) within our window
        if not placed and ts_end:
            dt_end = datetime.fromtimestamp(int(ts_end), tz=timezone.utc)
            mi = _month_index(dt_end)
            if 0 <= mi <= 11:
                proj[mi] = round(amount_usd, 2)
    else:
        if not ts_end:
            return proj
        # Monthly: advance until first billing date within window
        dt = datetime.fromtimestamp(int(ts_end), tz=timezone.utc)
        # Go back to find first billing in 2026
        while dt > PERIOD_START:
            prev = _add_months(dt, -1)
            if prev < PERIOD_START:
                break
            dt = prev
        while dt < PERIOD_END:
            mi = _month_index(dt)
            if 0 <= mi <= 11:
                proj[mi] = round(amount_usd, 2)
            dt = _add_months(dt, 1)

    return proj


def build_rows(subs):
    """
    Build one row per unique customer (by customer ID).
    Row format: [name, status, interval, base_usd, proj[12], next_invoice_str]
    Only USD subscriptions are included in projections.
    Non-USD amounts shown as base_usd=0 but customer still appears.
    """
    # Group subscriptions by customer ID — keep most severe status
    priority = {"Past due": 3, "Unpaid": 2, "Cancelled": 1, "Active": 0}
    customers = {}  # cust_id → dict

    for sub in subs:
        cust = sub.customer
        if isinstance(cust, str):
            cust_id, name, email, country = cust, "", "", ""
        else:
            cust_id = getattr(cust, "id", "") or ""
            name    = (getattr(cust, "name", "") or "").strip()
            email   = (getattr(cust, "email", "") or "").strip()
            addr    = getattr(cust, "address", None)
            country = (getattr(addr, "country", None) or "").upper() if addr else ""

        display = name or email or cust_id
        label   = stripe_status_to_label(sub.status)

        try:
            sub_dict = sub.to_dict()
        except Exception:
            sub_dict = {}

        items_data = sub_dict.get("items", {}).get("data", [])
        item = items_data[0] if items_data else {}
        price = item.get("price", {}) or {}
        amount   = (price.get("unit_amount") or 0)
        currency = (price.get("currency") or "usd").lower()
        rec      = (price.get("recurring") or {})
        interval = "Annual" if rec.get("interval") == "year" else "Monthly"
        amount_usd = round(amount / 100, 2) if currency == "usd" else 0.0

        # Next invoice date
        next_inv = ""
        try:
            ts = None
            if items_data:
                ts = items_data[0].get("current_period_end")
            if not ts:
                ts = sub_dict.get("billing_cycle_anchor")
            if ts:
                next_inv = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%b %d, %Y")
        except Exception:
            pass

        proj = _compute_projections(sub_dict, amount_usd, interval)

        if cust_id not in customers:
            customers[cust_id] = {
                "name":       display,
                "status":     label,
                "interval":   interval,
                "amount_usd": amount_usd,
                "proj":       proj,
                "next_inv":   next_inv,
                "country":    country,
            }
        else:
            ex = customers[cust_id]
            # Escalate status if worse
            if priority.get(label, 0) > priority.get(ex["status"], 0):
                ex["status"]   = label
                ex["next_inv"] = next_inv
            # Sum projections (customer may have multiple subs)
            ex["proj"]       = [round(a + b, 2) for a, b in zip(ex["proj"], proj)]
            ex["amount_usd"] = round(ex["amount_usd"] + amount_usd, 2)

    rows = []
    for info in customers.values():
        rows.append([
            info["name"],         # 0
            info["status"],       # 1
            info["interval"],     # 2
            info["amount_usd"],   # 3
            info["proj"],         # 4
            info["next_inv"],     # 5
            info.get("country",""), # 6
        ])

    rows.sort(key=lambda r: r[3], reverse=True)
    return rows


def compute_totals(rows):
    totals  = [0.0] * 12
    active  = [0.0] * 12
    problem = [0.0] * 12
    for r in rows:
        for i, v in enumerate(r[4]):
            totals[i] += v
            if r[1] == "Active":
                active[i] += v
            elif r[1] in ("Past due", "Unpaid"):
                problem[i] += v
    return (
        [round(x, 2) for x in totals],
        [round(x, 2) for x in active],
        [round(x, 2) for x in problem],
    )


def compute_subscription_metrics(subs):
    """MRR/ARR from active USD subscriptions."""
    monthly_mrr = 0.0
    annual_arr  = 0.0
    monthly_count = 0
    annual_count  = 0

    for sub in subs:
        if stripe_status_to_label(sub.status) != "Active":
            continue
        try:
            sub_dict = sub.to_dict()
            items = sub_dict.get("items", {}).get("data", [])
            if not items:
                continue
            price    = items[0].get("price", {}) or {}
            amount   = price.get("unit_amount", 0) or 0
            currency = (price.get("currency", "usd") or "usd").lower()
            interval = (price.get("recurring", {}) or {}).get("interval", "month")
            if currency != "usd" or not amount:
                continue
            if interval == "year":
                annual_arr   += amount / 100
                annual_count += 1
            else:
                monthly_mrr   += amount / 100
                monthly_count += 1
        except Exception:
            continue

    return {
        "monthly_mrr":   round(monthly_mrr, 2),
        "annual_arr":    round(annual_arr, 2),
        "annual_mrr":    round(annual_arr / 12, 2),
        "total_mrr":     round(monthly_mrr + annual_arr / 12, 2),
        "monthly_count": monthly_count,
        "annual_count":  annual_count,
    }


def fetch_today_invoices(subs):
    """Fetch invoices paid in last 24h via Invoice.list, with FX rate USD conversion."""
    import time
    since = int(time.time()) - 86400
    results = []
    try:
        params = {
            "status":   "paid",
            "created":  {"gte": since},
            "limit":    100,
        }
        while True:
            page = stripe.Invoice.list(**params)
            for inv in page.data:
                try:
                    d      = inv.to_dict()
                    amount = _to_usd(d.get("amount_paid", 0), d.get("currency", "usd"))
                    ts     = d.get("status_transitions", {}).get("paid_at") or d.get("created") or 0
                    cname  = d.get("customer_name") or d.get("customer_email") or "Unknown"
                    time_str = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%H:%M UTC") if ts else ""
                    if amount > 0:
                        results.append({"name": cname, "amount": amount, "time": time_str})
                except Exception:
                    continue
            if not page.has_more:
                break
            params["starting_after"] = page.data[-1].id
    except Exception as e:
        print(f"  Warning: could not fetch today's invoices: {e}")
    results.sort(key=lambda x: x["time"], reverse=True)
    return results


# ── FX conversion (no Stripe permissions needed) ────────────────────────────
_FX_RATES = {}   # populated once at startup: {'EUR': 0.92, 'BRL': 5.1, ...}

def _load_fx_rates():
    """Fetch current USD exchange rates from open.er-api.com (free, no auth)."""
    import urllib.request
    global _FX_RATES
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=8) as r:
            data = json.loads(r.read().decode())
            _FX_RATES = data.get("rates", {})
            print(f"  FX rates loaded ({len(_FX_RATES)} currencies)")
    except Exception as e:
        print(f"  Warning: could not load FX rates: {e}. Using 1:1 fallback.")

def _to_usd(amount_cents, currency):
    """Convert amount in cents (given currency) to USD float using current FX rates."""
    amount = (amount_cents or 0) / 100
    cur = (currency or "usd").upper()
    if cur == "USD":
        return round(amount, 2)
    rate = _FX_RATES.get(cur, 0)
    if rate > 0:
        return round(amount / rate, 2)
    return round(amount, 2)  # fallback: treat as USD if rate unknown


def _fetch_month_collected(mi):
    """Fetch total USD collected for a single month index (0=Jan..11=Dec)."""
    month_start = datetime(2026, mi + 1, 1, tzinfo=timezone.utc)
    month_end   = datetime(2027, 1, 1, tzinfo=timezone.utc) if mi == 11 else datetime(2026, mi + 2, 1, tzinfo=timezone.utc)
    start_ts, end_ts = int(month_start.timestamp()), int(month_end.timestamp())
    total = 0.0
    try:
        params = {"status": "paid", "created": {"gte": start_ts, "lte": end_ts}, "limit": 100}
        while True:
            page = stripe.Invoice.list(**params)
            for inv in page.data:
                try:
                    d      = inv.to_dict()
                    amount = _to_usd(d.get("amount_paid", 0), d.get("currency", "usd"))
                    ts     = d.get("status_transitions", {}).get("paid_at") or d.get("created") or 0
                    if amount > 0 and ts:
                        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                        if _month_index(dt) == mi:
                            total = round(total + amount, 2)
                except Exception:
                    continue
            if not page.has_more:
                break
            params["starting_after"] = page.data[-1].id
    except Exception as e:
        print(f"  Warning fetching month {mi+1}: {e}")
    return total


def fetch_monthly_collected():
    """
    Fetch collected USD per month for Jan-Dec 2026.
    Past months are cached in collected_cache.json — values are frozen once a
    month completes so daily FX rate changes don't alter historical figures.
    Current and future months are always re-fetched.
    """
    cache_file = "collected_cache.json"
    try:
        with open(cache_file) as f:
            cache = json.load(f)
    except Exception:
        cache = {}

    now = datetime.now(timezone.utc)
    # Current month index in 2026 (0-11), or 11 if we're in 2027+
    if now.year == 2026:
        current_mi = now.month - 1
    elif now.year > 2026:
        current_mi = 12  # all months are past
    else:
        current_mi = 0   # all months are future

    collected = [0.0] * 12
    cache_updated = False

    for mi in range(12):
        key = f"2026-{mi+1:02d}"
        if mi < current_mi and key in cache:
            # Past month already cached — use frozen value
            collected[mi] = cache[key]
        else:
            # Current month or not yet cached — fetch fresh
            val = _fetch_month_collected(mi)
            collected[mi] = val
            # Freeze past months into cache
            if mi < current_mi:
                cache[key] = val
                cache_updated = True
                print(f"  Cached {key}: ${val:,.2f}")

    if cache_updated:
        try:
            with open(cache_file, "w") as f:
                json.dump(cache, f, indent=2)
            print(f"  collected_cache.json updated ({sum(1 for v in cache.values() if v>0)} months)")
        except Exception as e:
            print(f"  Warning: could not save cache: {e}")

    return collected




def render_html(rows, totals, active_tot, problem_tot, synced, metrics, today_invoices, monthly_collected):
    rows_js          = json.dumps(rows, ensure_ascii=False)
    totals_js        = json.dumps(totals)
    collected_js     = json.dumps(monthly_collected)
    metrics_js       = json.dumps(metrics)
    today_total      = sum(i["amount"] for i in today_invoices)
    today_count      = len(today_invoices)
    today_total_fmt  = f"${today_total:,.0f}" if today_total else "$0"
    today_rows_html  = "".join(
        f'<tr style="border-bottom:0.5px solid var(--border2)">'
        f'<td style="padding:9px 12px;font-weight:500">{i["name"]}</td>'
        f'<td style="padding:9px 12px;text-align:right;font-variant-numeric:tabular-nums">'
        f'${i["amount"]:,.2f}</td>'
        f'<td style="padding:9px 12px;color:var(--text2);font-size:12px">{i["time"]}</td></tr>'
        for i in today_invoices
    )
    today_section = ""
    if today_invoices:
        today_section = f"""
  <div class="card" style="margin-bottom:1.5rem">
    <div class="card-title">Today&#39;s transactions</div>
    <div style="overflow-x:auto;border-radius:var(--radius);border:0.5px solid var(--border2)">
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="background:var(--bg2)">
          <th style="text-align:left;padding:8px 12px;font-size:11px;font-weight:500;color:var(--text2);text-transform:uppercase;letter-spacing:.04em;border-bottom:0.5px solid var(--border2)">Customer</th>
          <th style="text-align:right;padding:8px 12px;font-size:11px;font-weight:500;color:var(--text2);text-transform:uppercase;letter-spacing:.04em;border-bottom:0.5px solid var(--border2)">Amount</th>
          <th style="text-align:left;padding:8px 12px;font-size:11px;font-weight:500;color:var(--text2);text-transform:uppercase;letter-spacing:.04em;border-bottom:0.5px solid var(--border2)">Time</th>
        </tr></thead>
        <tbody>{today_rows_html}</tbody>
      </table>
    </div>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Floori.io — Revenue Dashboard</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#ffffff;--bg2:#f5f5f3;--bg3:#eeece6;
  --text:#1a1a18;--text2:#6b6a65;--text3:#9e9d98;
  --border:rgba(0,0,0,0.10);--border2:rgba(0,0,0,0.07);
  --green:#3B6D11;--green-bg:#EAF3DE;--gbar:#6FAF2A;
  --red:#A32D2D;--red-bg:#FCEBEB;
  --amber:#854F0B;--amber-bg:#FAEEDA;
  --blue:#185FA5;--blue-bg:#E8F0FB;--bbar:#5B9BD5;
  --gray:#5F5E5A;--gray-bg:#F1EFE8;--stripe:#635BFF;
  --r:8px;--rl:12px;
  --font:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
}}
@media(prefers-color-scheme:dark){{
  :root{{
    --bg:#1c1c1a;--bg2:#242422;--bg3:#2c2c2a;
    --text:#e8e6df;--text2:#9e9d98;--text3:#6b6a65;
    --border:rgba(255,255,255,0.10);--border2:rgba(255,255,255,0.06);
    --green:#9FE1CB;--green-bg:#085041;--gbar:#4D9A2A;
    --red:#F09595;--red-bg:#501313;
    --amber:#FAC775;--amber-bg:#412402;
    --blue:#7EB4E8;--blue-bg:#0D2A4A;--bbar:#2A5A8A;
    --gray:#B4B2A9;--gray-bg:#2C2C2A;
  }}
}}
body{{font-family:var(--font);background:var(--bg3);color:var(--text);font-size:14px;min-height:100vh}}
.wrap{{max-width:1140px;margin:0 auto;padding:1.5rem}}
.topbar{{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.75rem;flex-wrap:wrap;gap:1rem}}
.topbar h1{{font-size:16px;font-weight:500;display:flex;align-items:center;gap:8px}}
.si{{color:var(--stripe)}}
.synced{{font-size:11px;color:var(--text3);margin-top:3px}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:1.5rem}}
.mc{{background:var(--bg);border:0.5px solid var(--border2);border-radius:var(--rl);padding:1.1rem 1rem}}
.mc .lbl{{font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}}
.mc .val{{font-size:24px;font-weight:500;line-height:1.1}}
.mc .sub{{font-size:11px;color:var(--text3);margin-top:5px}}
.charts-row{{display:grid;grid-template-columns:3fr 2fr;gap:12px;margin-bottom:1.5rem}}
.card{{background:var(--bg);border:0.5px solid var(--border2);border-radius:var(--rl);padding:1.1rem 1.25rem}}
.card-title{{font-size:12px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:.04em;margin-bottom:14px}}
/* bar chart */
.bchart{{display:flex;gap:5px;align-items:flex-end;height:130px;margin-bottom:4px}}
.bcol{{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:2px;cursor:pointer;transition:opacity .15s}}
.bcol:hover{{opacity:.75}}
.bbar{{width:100%;border-radius:3px 3px 0 0;transition:all .2s}}
.blbl{{font-size:10px;color:var(--text3);transition:color .2s;white-space:nowrap}}
.blbl.sel{{color:var(--green);font-weight:600}}
.bval{{font-size:9px;color:var(--text3);white-space:nowrap;overflow:hidden;max-width:100%;text-align:center}}
.bval.sel{{color:var(--green);font-weight:600}}
.yr-div{{width:1px;background:var(--border);margin:0 1px;align-self:stretch}}
.chart-legend{{display:flex;gap:12px;font-size:11px;color:var(--text2);margin-top:4px}}
.chart-legend span{{display:flex;align-items:center;gap:4px}}
.dot{{width:10px;height:10px;border-radius:2px;display:inline-block}}
/* comparison card */
.cmp-nav{{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}}
.cmp-mo{{font-size:15px;font-weight:500}}
.nav-btn{{background:var(--bg2);border:0.5px solid var(--border);border-radius:var(--r);padding:4px 10px;cursor:pointer;color:var(--text);font-size:13px}}
.nav-btn:disabled{{opacity:.35;cursor:default}}
.cmp-bars{{display:flex;gap:16px;margin-bottom:10px}}
.cmp-col{{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px}}
.cmp-amt{{font-size:15px;font-weight:600;font-variant-numeric:tabular-nums;line-height:1}}
.cmp-bar-area{{width:100%;height:80px;display:flex;align-items:flex-end;overflow:hidden}}
.cmp-bar{{width:100%;border-radius:4px 4px 0 0;transition:height .3s ease;min-height:0}}
.cmp-lbl{{font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:.04em;margin-top:2px}}
.cmp-diff{{text-align:center;font-size:12px;padding:8px;border-radius:var(--r);margin-top:4px}}
/* row2 */
.row2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:1.5rem}}
.kv{{display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:0.5px solid var(--border2);font-size:13px}}
.kv:last-child{{border-bottom:none}}
.kv .k{{color:var(--text2)}}
.kv .v{{font-weight:500}}
.kv .v.red{{color:var(--red)}}
.kv .v.green{{color:var(--green)}}
/* invoices */
.inv-wrap{{border-radius:var(--r);border:0.5px solid var(--border2);overflow:hidden}}
.inv-table{{width:100%;border-collapse:collapse;font-size:13px}}
.inv-table th{{font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.04em;padding:7px 10px;background:var(--bg2);border-bottom:0.5px solid var(--border2);text-align:left}}
.inv-table th.r,.inv-table td.r{{text-align:right}}
.inv-table td{{padding:8px 10px;border-bottom:0.5px solid var(--border2);vertical-align:middle}}
.inv-table tr:last-child td{{border-bottom:none}}
.inv-table tr:hover td{{background:var(--bg2)}}
.empty{{text-align:center;color:var(--text3);font-size:13px;padding:1.5rem}}
/* table */
.tbl-section{{background:var(--bg);border:0.5px solid var(--border2);border-radius:var(--rl);padding:1.1rem 1.25rem}}
.tbl-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:8px;flex-wrap:wrap}}
.tbl-controls{{display:flex;gap:8px}}
.tbl-controls input,.tbl-controls select{{background:var(--bg);border:0.5px solid var(--border);border-radius:var(--r);padding:5px 9px;font-size:13px;color:var(--text)}}
.tbl-controls input{{width:155px}}
.tbl-wrap{{overflow-x:auto;border-radius:var(--r);border:0.5px solid var(--border2)}}
table{{width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed}}
thead th{{font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.04em;padding:8px 12px;background:var(--bg2);border-bottom:0.5px solid var(--border2);text-align:left;white-space:nowrap}}
th.r,td.r{{text-align:right}}
tbody tr{{border-bottom:0.5px solid var(--border2);transition:background .1s}}
tbody tr:last-child{{border-bottom:none}}
tbody tr:hover{{background:var(--bg2)}}
tbody td{{padding:9px 12px;vertical-align:middle;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.badge{{display:inline-flex;font-size:11px;padding:2px 8px;border-radius:20px;font-weight:500}}
.b-active{{background:var(--green-bg);color:var(--green)}}
.b-pastdue{{background:var(--red-bg);color:var(--red)}}
.b-unpaid{{background:var(--amber-bg);color:var(--amber)}}
.freq{{font-size:11px;background:var(--bg2);padding:1px 6px;border-radius:20px;color:var(--text3)}}
.pag{{display:flex;align-items:center;gap:8px;margin-top:12px;font-size:13px;color:var(--text2)}}
.pag button{{background:var(--bg);border:0.5px solid var(--border2);border-radius:var(--r);padding:4px 10px;cursor:pointer;color:var(--text);font-size:12px}}
.pag button:disabled{{opacity:.35;cursor:default}}
.pag button:not(:disabled):hover{{background:var(--bg2)}}
#ct-lbl{{margin-left:auto;font-size:12px}}
@media(max-width:700px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.charts-row,.row2{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="wrap">

  <div class="topbar">
    <div>
      <h1><span class="si">◈</span> Floori.io — Revenue Dashboard</h1>
      <p class="synced">Last synced: {synced} · Auto-updated weekdays at 9:30 AM BRT</p>
    </div>
  </div>

  <div class="metrics">
    <div class="mc">
      <div class="lbl">Total MRR</div>
      <div class="val" style="color:var(--green)">${metrics["total_mrr"]:,.0f}</div>
      <div class="sub">active USD · monthly + annual ÷ 12</div>
    </div>
    <div class="mc">
      <div class="lbl">Monthly revenue</div>
      <div class="val">${metrics["monthly_mrr"]:,.0f}<span style="font-size:13px;font-weight:400;color:var(--text3)">/mo</span></div>
      <div class="sub">{metrics["monthly_count"]} monthly subscribers</div>
    </div>
    <div class="mc">
      <div class="lbl">Annual revenue</div>
      <div class="val">${metrics["annual_arr"]:,.0f}<span style="font-size:13px;font-weight:400;color:var(--text3)">/yr</span></div>
      <div class="sub">{metrics["annual_count"]} annual · ${metrics["annual_mrr"]:,.0f}/mo equiv.</div>
    </div>
    <div class="mc">
      <div class="lbl">Collected today</div>
      <div class="val" style="color:{'var(--green)' if today_total>0 else 'var(--text3)'}">{today_total_fmt}</div>
      <div class="sub">{today_count} payment{"s" if today_count != 1 else ""} · USD equiv.</div>
    </div>
  </div>

  <div class="charts-row">
    <!-- Card 1: Full year expected (clickable to select month) -->
    <div class="card">
      <div class="card-title">Expected cashflow — Jan to Dec 2026 <span style="font-size:10px;font-weight:400;color:var(--text3);text-transform:none;letter-spacing:0">(click month to filter)</span></div>
      <div class="bchart" id="barchart"></div>
      <div class="chart-legend">
        <span><span class="dot" style="background:var(--gbar)"></span>Expected (active subs)</span>
      </div>
    </div>
    <!-- Card 2: Expected vs Collected for selected month -->
    <div class="card">
      <div class="cmp-nav">
        <button class="nav-btn" id="cmp-prev" onclick="prevMonth()">←</button>
        <span class="cmp-mo" id="cmp-mo-label">—</span>
        <button class="nav-btn" id="cmp-next" onclick="nextMonth()">→</button>
      </div>
      <div class="cmp-bars">
        <div class="cmp-col">
          <div class="cmp-amt" id="cval-exp" style="color:var(--green)">—</div>
          <div class="cmp-bar-area">
            <div class="cmp-bar" id="cbar-exp" style="background:var(--gbar)"></div>
          </div>
          <div class="cmp-lbl">Expected</div>
        </div>
        <div class="cmp-col">
          <div class="cmp-amt" id="cval-col" style="color:var(--blue)">—</div>
          <div class="cmp-bar-area">
            <div class="cmp-bar" id="cbar-col" style="background:var(--bbar)"></div>
          </div>
          <div class="cmp-lbl">Collected</div>
        </div>
      </div>
      <div class="cmp-diff" id="cmp-diff"></div>
    </div>
  </div>

  <div class="row2">
    <div class="card">
      <div class="card-title" id="sel-title">Selected period</div>
      <div class="kv"><span class="k">Expected revenue</span><span class="v green" id="sel-expected">—</span></div>
      <div class="kv"><span class="k">Active paying customers</span><span class="v" id="sel-active-count">—</span></div>
      <div class="kv"><span class="k">At risk (problem accounts)</span><span class="v red" id="sel-problem">—</span></div>
    </div>
    <div class="card">
      <div class="card-title">Recent payments <span style="font-weight:400;font-size:10px;color:var(--text3);text-transform:none;letter-spacing:0">(last 24h · USD equiv.)</span></div>
      {"<div class='inv-wrap'><table class='inv-table'><thead><tr><th>Customer</th><th class='r'>Amount</th><th>Time</th></tr></thead><tbody>" + today_rows_html + "</tbody></table></div>" if today_invoices else "<div class='empty'>No payments in the last 24h</div>"}
    </div>
  </div>

  <div class="tbl-section">
    <div class="tbl-header">
      <div class="card-title" id="tbl-title" style="margin-bottom:0">All customers</div>
      <div class="tbl-controls">
        <input id="search" placeholder="Search…" oninput="renderTable()">
        <select id="flt" onchange="updateAll()">
          <option value="all">All</option>
          <option value="Active">Active</option>
          <option value="problem">Problem accounts</option>
        </select>
      </div>
    </div>
    <p id="tbl-hint" style="font-size:12px;color:var(--text3);margin-bottom:10px"></p>
    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th style="width:28%">Customer</th>
          <th style="width:9%">Country</th>
          <th style="width:12%">Status</th>
          <th style="width:14%">Next invoice</th>
          <th style="width:12%" class="r col-annual">Annual total</th>
          <th style="width:12%" class="r">Base amount</th>
          <th style="width:8%">Interval</th>
        </tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
    <div class="pag">
      <button id="prev-pg" onclick="go(-1)" disabled>← Prev</button>
      <span id="pg-info">Page 1 of 1</span>
      <button id="next-pg" onclick="go(1)">Next →</button>
      <span id="ct-lbl"></span>
    </div>
  </div>

</div>
<script>
const MONTHS=["Jan 2026","Feb 2026","Mar 2026","Apr 2026","May 2026","Jun 2026","Jul 2026","Aug 2026","Sep 2026","Oct 2026","Nov 2026","Dec 2026"];
const MO_SHORT=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const D={rows_js}.filter(r=>r[1]!=="Cancelled");
const COLLECTED={collected_js};
const BC={{"Active":"b-active","Past due":"b-pastdue","Unpaid":"b-unpaid"}};
const fmt=v=>v===0?"—":(v<0?"-":"")+new Intl.NumberFormat("en-US",{{style:"currency",currency:"USD",maximumFractionDigits:0}}).format(Math.abs(v));
const fmtS=v=>Math.abs(v)>=1000?(v<0?"-":"")+"$"+(Math.abs(v)/1000).toFixed(1)+"k":"$"+Math.round(v);

let mi=4,pg=1,sf="all"; // mi: 0-11=Jan-Dec, -1=Year; default May (index 4)
const PS=15;

function byStatus(){{
  const f=sf;
  return D.filter(r=>f==="all"||(f==="Active"&&r[1]==="Active")||(f==="problem"&&(r[1]==="Past due"||r[1]==="Unpaid")));
}}

function prevMonth(){{if(mi>0)setMonth(mi-1);else if(mi===-1)setMonth(11);}}
function nextMonth(){{if(mi<11)setMonth(mi+1);else setMonth(-1);}}

function flag(c){{if(!c||c.length!==2)return"";return String.fromCodePoint(c.charCodeAt(0)+127397)+String.fromCodePoint(c.charCodeAt(1)+127397);}}

function setMonth(i){{
  mi=i;
  const isYr=mi===-1;
  document.getElementById("cmp-mo-label").textContent=isYr?"Full Year 2026":MONTHS[mi];
  document.getElementById("cmp-prev").disabled=false;
  document.getElementById("cmp-next").disabled=false;
  document.getElementById("sel-title").textContent=isYr?"Full Year 2026":MONTHS[mi];
  document.getElementById("tbl-title").textContent=isYr?"All customers — Full Year 2026":"Customers with revenue in "+MONTHS[mi];
  document.getElementById("tbl-hint").textContent=isYr?"Showing all customers across Jan\u2013Dec 2026":"Only customers billed this month · Select 'Year' in the chart above to see all.";
  document.querySelectorAll(".col-annual").forEach(el=>el.style.display=isYr?"none":"");
  updateAll();
}}

function updateAll(){{
  sf=document.getElementById("flt").value;
  updateSelCard();
  renderExpectedChart();
  updateCmpCard();
  pg=1; _render();
}}

function updateSelCard(){{
  const all=D;
  const problems=all.filter(r=>r[1]==="Past due"||r[1]==="Unpaid");
  let expected,activeCount,problemAmt;
  if(mi===-1){{
    expected=MONTHS.reduce((s,_,i)=>s+expectedForMonth(i),0);
    activeCount=D.filter(r=>r[1]==="Active"&&r[4].some(v=>v>0)).length;
    problemAmt=problems.reduce((s,r)=>s+r[4].reduce((a,v)=>a+v,0),0);
  }}else{{
    expected=expectedForMonth(mi);
    activeCount=D.filter(r=>r[1]==="Active"&&r[4][mi]>0).length;
    problemAmt=problems.reduce((s,r)=>s+r[4][mi],0);
  }}
  document.getElementById("sel-expected").textContent=expected>0?fmt(expected):"—";
  document.getElementById("sel-active-count").textContent=activeCount+" customers";
  document.getElementById("sel-problem").textContent=problemAmt>0?"-"+fmtS(problemAmt):problems.length+" accounts";
}}

const TODAY_MI=4; // May 2026 = index 4; update each new year
function expectedForMonth(i){{
  // Past/current months: all subs (they were expected to bill then)
  // Future months: active only (what we can realistically expect)
  const subs=i<=TODAY_MI?D:D.filter(r=>r[1]==="Active");
  return subs.reduce((s,r)=>s+r[4][i],0);
}}
function renderExpectedChart(){{
  const mt=MONTHS.map((_,i)=>expectedForMonth(i));
  const yt=mt.reduce((a,v)=>a+v,0);
  const mx=Math.max(...mt,yt)||1;
  let html="";
  mt.forEach((v,i)=>{{
    const sel=mi===i;
    const h=Math.max(3,Math.round((v/mx)*100));
    html+=`<div class="bcol" onclick="setMonth(${{i}})">
      <span class="bval${{sel?" sel":""}}">${{v>0?fmtS(v):""}}</span>
      <div class="bbar" style="height:${{h}}px;background:${{sel?"var(--green)":"var(--gbar)"}};flex-shrink:0"></div>
      <span class="blbl${{sel?" sel":""}}">${{MO_SHORT[i]}}</span>
    </div>`;
  }});
  const selYr=mi===-1;
  const hYr=Math.max(3,Math.round((yt/mx)*100));
  html+=`<div class="yr-div"></div>
  <div class="bcol" onclick="setMonth(-1)">
    <span class="bval${{selYr?" sel":""}}">${{fmtS(yt)}}</span>
    <div class="bbar" style="height:${{hYr}}px;background:${{selYr?"var(--green)":"#B8DFA0"}};flex-shrink:0"></div>
    <span class="blbl${{selYr?" sel":""}}">Year</span>
  </div>`;
  document.getElementById("barchart").innerHTML=html;
  // Show selected value in card title
  const selVal=mi===-1?fmtS(yt):(mt[mi]>0?fmtS(mt[mi]):"—");
  document.querySelector('.card-title[style*=""]') ;
  const chartTitle=document.querySelector("#barchart").previousElementSibling;
  if(chartTitle) chartTitle.innerHTML='Expected cashflow — Jan to Dec 2026 <span style="font-weight:400;color:var(--text3);text-transform:none;letter-spacing:0;font-size:10px">(click month) &nbsp; <strong style="color:var(--green)">'+(mi===-1?"Year: "+fmtS(yt):MONTHS[mi]+": "+selVal)+'</strong></span>';
}}

function updateCmpCard(){{
  const isYr=mi===-1;
  let exp,col;
  if(isYr){{
    exp=MONTHS.reduce((s,_,i)=>s+expectedForMonth(i),0);
    col=COLLECTED.reduce((a,v)=>a+v,0);
  }}else{{
    exp=expectedForMonth(mi);
    col=COLLECTED[mi]||0;
  }}
  const mx=Math.max(exp,col)||1;
  const hExp=Math.max(8,Math.round((exp/mx)*80));
  const hCol=Math.max(col>0?8:0,Math.round((col/mx)*80));
  document.getElementById("cbar-exp").style.height=hExp+"px";
  document.getElementById("cbar-col").style.height=hCol+"px";
  document.getElementById("cval-exp").textContent=exp>0?fmt(exp):"—";
  document.getElementById("cval-col").textContent=col>0?fmt(col):"—";
  const diff=col-exp;
  const diffEl=document.getElementById("cmp-diff");
  if(col===0&&exp===0){{diffEl.textContent="";diffEl.style.background="";return;}}
  const pct=exp>0?Math.round((col/exp)*100):0;
  if(diff>=0){{
    diffEl.innerHTML=`<span style="color:var(--green);font-weight:500">+${{fmt(diff)}}</span> <span style="color:var(--text3)">(${{pct}}% of expected)</span>`;
    diffEl.style.background="var(--green-bg)";
  }}else{{
    diffEl.innerHTML=`<span style="color:var(--red);font-weight:500">${{fmt(diff)}}</span> <span style="color:var(--text3)">(${{pct}}% of expected collected)</span>`;
    diffEl.style.background="var(--red-bg)";
  }}
}}

function getFiltered(){{
  const q=document.getElementById("search").value.toLowerCase();
  const base=byStatus();
  const byM=mi>=0?base.filter(r=>r[4][mi]>0):base;
  return byM.filter(r=>!q||r[0].toLowerCase().includes(q));
}}

function renderTable(){{pg=1;_render();}}
function go(d){{const tp=Math.ceil(getFiltered().length/PS);pg=Math.max(1,Math.min(tp,pg+d));_render();}}
function _render(){{
  const f=getFiltered(),tp=Math.max(1,Math.ceil(f.length/PS)),rows=f.slice((pg-1)*PS,pg*PS);
  document.getElementById("pg-info").textContent=`Page ${{pg}} of ${{tp}}`;
  document.getElementById("prev-pg").disabled=pg<=1;
  document.getElementById("next-pg").disabled=pg>=tp;
  document.getElementById("ct-lbl").textContent=f.length+" customers";
  document.getElementById("tbody").innerHTML=rows.map((r,i)=>{{
    const prob=r[1]==="Past due"||r[1]==="Unpaid";
    const annualTotal=r[2]==="Annual"?r[3]:r[3]*12;
    const ctry=r[6]||"";
    return `<tr>
      <td style="font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${{r[0]}}</td>
      <td style="font-size:16px;text-align:center" title="${{ctry}}">${{flag(ctry)}}</td>
      <td><span class="badge ${{BC[r[1]]||"b-unpaid"}}">${{r[1]}}</span></td>
      <td style="font-size:12px;color:${{prob?"var(--red)":"var(--text2)"}};font-weight:${{prob?500:400}}">${{r[5]||"—"}}</td>
      <td class="r col-annual" style="color:var(--text2)">${{annualTotal>0?fmt(annualTotal):"—"}}</td>
      <td class="r" style="color:var(--text2)">$${{r[3].toLocaleString()}}</td>
      <td><span class="freq">${{r[2]}}</span></td>
    </tr>`;
  }}).join("");
}}

setMonth(4); // default: May 2026
</script>
</body>
</html>"""

if __name__ == "__main__":
    print("Fetching subscriptions from Stripe...")
    subs = fetch_all_subscriptions()
    print(f"  {len(subs)} subscriptions fetched")

    print("Building rows from Stripe data...")
    rows = build_rows(subs)
    print(f"  {len(rows)} unique customers")

    totals, active_tot, problem_tot = compute_totals(rows)

    print("Computing subscription metrics...")
    metrics = compute_subscription_metrics(subs)
    print(f"  MRR: ${metrics['total_mrr']:,.0f} (monthly ${metrics['monthly_mrr']:,.0f} + annual equiv. ${metrics['annual_mrr']:,.0f})")

    print("Loading FX rates...")
    _load_fx_rates()

    print("Fetching today's invoices...")
    today_invoices = fetch_today_invoices(subs)
    print(f"  {len(today_invoices)} invoice(s) paid in last 24h")

    print("Fetching monthly collected amounts...")
    monthly_collected = fetch_monthly_collected()
    print(f"  Collected by month: {[round(x) for x in monthly_collected]}")

    synced = datetime.now(timezone.utc).strftime("%b %d, %Y at %H:%M UTC")
    html = render_html(rows, totals, active_tot, problem_tot, synced, metrics, today_invoices, monthly_collected)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  index.html written — {len(rows)} customers, synced {synced}")
