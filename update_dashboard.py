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
    params = {"limit": 100, "status": "all", "expand": ["data.customer", "data.items.data.price"]}
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


# ── Country name → ISO 2-letter code normalization ──────────────────────────
_COUNTRY_NORM = {
    "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US", "USA": "US",
    "AUSTRALIA": "AU", "UNITED KINGDOM": "GB", "GREAT BRITAIN": "GB",
    "BRAZIL": "BR", "BRASIL": "BR", "NETHERLANDS": "NL", "HOLLAND": "NL",
    "SOUTH AFRICA": "ZA", "ARGENTINA": "AR", "MEXICO": "MX",
    "JAPAN": "JP", "SINGAPORE": "SG", "DENMARK": "DK", "ITALY": "IT",
    "NEW ZEALAND": "NZ", "CANADA": "CA", "GERMANY": "DE", "FRANCE": "FR",
    "SPAIN": "ES", "PORTUGAL": "PT", "ISRAEL": "IL", "MOROCCO": "MA",
    "BELGIUM": "BE", "CZECH REPUBLIC": "CZ", "CZECHIA": "CZ",
    "AUSTRIA": "AT", "SWITZERLAND": "CH", "SWEDEN": "SE",
    "NORWAY": "NO", "FINLAND": "FI", "POLAND": "PL",
    "INDONESIA": "ID", "MALAYSIA": "MY", "THAILAND": "TH",
    "COLOMBIA": "CO", "CHILE": "CL", "PERU": "PE", "URUGUAY": "UY",
    "INDIA": "IN", "CHINA": "CN", "UAE": "AE",
    "UNITED ARAB EMIRATES": "AE",
}

def _normalize_country(raw: str) -> str:
    if not raw:
        return ""
    up = raw.strip().upper()
    if len(up) == 2:
        return up
    return _COUNTRY_NORM.get(up, up[:2] if len(up) >= 2 else up)


# ── Currency → ISO country fallback (when address.country is blank) ──────────
_CURRENCY_COUNTRY = {
    "brl": "BR", "aud": "AU", "gbp": "GB", "jpy": "JP",
    "mxn": "MX", "cad": "CA", "nzd": "NZ", "zar": "ZA",
    "ars": "AR", "sgd": "SG", "dkk": "DK", "nok": "NO",
    "sek": "SE", "chf": "CH", "pln": "PL", "czk": "CZ",
    "ils": "IL", "mad": "MA", "idr": "ID", "myr": "MY",
    "thb": "TH", "cop": "CO", "clp": "CL", "inr": "IN",
    "aed": "AE", "usd": "US",
}

# ── HubSpot customer type mapping (generated from HubSpot companies export) ──
# Source: CompanyType field matched via Stripe Customer ID and email
# Retailer includes: Retailer, Installer, Homecenter, Interior Designer
# Regenerate by re-running the HubSpot analysis script
_HS_TYPE_BY_ID    = {'cus_T3TFrqhVq8eVHk': 'Retailer', 'cus_STlDuRL46EA4EN': 'Manufacturer', 'cus_RJ2dcdzS4ioTvy': 'Retailer', 'cus_Ry23UPb2LLn0Oq': 'Retailer', 'cus_RL5GvO6tmwE5w3': 'Retailer', 'cus_RDCwLRjbBDvE6J': 'Retailer', 'cus_RYxK99M3PsOppx': 'Retailer', 'cus_R69QrXxgIlyHNK': 'Manufacturer', 'cus_QyCkTc5yw4HGjm': 'Retailer', 'cus_QvCf13IJ2jDfly': 'Distributor', 'cus_QklnP7CbOtSkGC': 'Retailer', 'cus_QoZ6CDMC8ggJ39': 'Retailer', 'cus_QSmtYIOQsnMBd0': 'Retailer', 'cus_QsYuhVg78c2W4s': 'Ecommerce', 'cus_QTnu08jf6w9M5X': 'Retailer', 'cus_QeIXr8M6ojVR76': 'Retailer', 'cus_QRAeZvoNSFWAnX': 'Retailer', 'cus_QMjHhyY2L8r2rU': 'Retailer', 'cus_QFEw1qBmJlNgLG': 'Retailer', 'cus_QCHjQfQb6Bl5en': 'Retailer', 'cus_Q7A89tVjYyJsX7': 'Retailer', 'cus_Q4lDeCN0FXbOk5': 'Retailer', 'cus_Q480QTq6PqkrVO': 'Retailer', 'cus_Q29hlcxe0oUJHw': 'Ecommerce', 'cus_Q41bO004wpe6Cd': 'Retailer', 'cus_Ktjh8jQXiAPCZq': 'Retailer', 'cus_PzT6766bw4H0D3': 'Retailer', 'cus_Q0H7h2188vzf6m': 'Retailer', 'cus_Pnw1owD8BKFfZy': 'Retailer', 'cus_PntvQV6o1JRmG3': 'Retailer', 'cus_RwBczpBwMqLt7Z': 'Retailer', 'cus_PmSZt7uQnmQuiB': 'Retailer', 'cus_PhCE8mlG6AobsH': 'Retailer', 'cus_QbxZNhlukJ6Yk1': 'Distributor', 'cus_PgotO3wZ43jp9U': 'Retailer', 'cus_Pg2RFSUTWPT0DL': 'Distributor', 'cus_Py5jpz08sH5jEs': 'Retailer', 'cus_PbBm0iXDU7VQQf': 'Retailer', 'cus_PhZMy7cJUDuhSm': 'Retailer', 'cus_PYOA48pwq2BWqy': 'Retailer', 'cus_PbRwYVLeojYFPw': 'Retailer', 'cus_PbCXe5cpJXXyKn': 'Retailer', 'cus_POR9rick4ssAHQ': 'Retailer', 'cus_PVdhPiIjX4X1AL': 'Retailer', 'cus_PVcO4CpkxNXPgP': 'Ecommerce', 'cus_PTizAlzduBFFKd': 'Retailer', 'cus_RQJKgmw67tiSPx': 'Distributor', 'cus_PTNqB8O0KhE3eh': 'Retailer', 'cus_PQAH8n2MxIBjj0': 'Retailer', 'cus_PNzFZ3mGSGz3xi': 'Retailer', 'cus_QkHAIE3wR7UCQl': 'Distributor', 'cus_PcGpu9Wbtqjlqh': 'Retailer', 'cus_PgoIc33Qzf1x8j': 'Retailer', 'cus_Q3bpUIdCwTnFJf': 'Distributor', 'cus_P9SbJ59vCf5sWl': 'Retailer', 'cus_P8hnd0Rol0sr6i': 'Retailer', 'cus_P6O9k4xpt3wXU7': 'Retailer', 'cus_P6bEhhdqlX0g3s': 'Retailer', 'cus_PAYonUGhfeHm7K': 'Retailer', 'cus_PNVNNd7fB6q3YU': 'Retailer', 'cus_P0YhtUssbEWzzJ': 'Retailer', 'cus_Oy3HciwpubU1fp': 'Retailer', 'cus_OvbwlyhtGrG0aR': 'Retailer', 'cus_OyZbPi82Phdaq5': 'Retailer', 'cus_OyxH0JM6sWofdG': 'Retailer', 'cus_P6UU1ST6fIjWiL': 'Retailer', 'cus_QN7o3x6z0BlIzK': 'Distributor', 'cus_QA05o4yRkro4VT': 'Retailer', 'cus_OqjJ1kI3MeKoXz': 'Retailer', 'cus_OxPyRXBYTA250V': 'Retailer', 'cus_OqTCvDP9OVg8e3': 'Retailer', 'cus_On9fa1sJC4vJae': 'Retailer', 'cus_P3U6N367cY1M50': 'Distributor', 'cus_OptrdAG6W6ASxs': 'Retailer', 'cus_OkkSMgqb1QXCiE': 'Retailer', 'cus_OqFzP6n8c8Phup': 'Retailer', 'cus_OiNL2xlvLevwBU': 'Retailer', 'cus_R0Pch4RjFv2t4n': 'Retailer', 'cus_Q8etqzXMxfPxX8': 'Retailer', 'cus_OizRfFRGRBSegw': 'Retailer', 'cus_Odw051wagIvtx7': 'Retailer', 'cus_OayXvajRi84ZoC': 'Retailer', 'cus_OoJE8Ajajbm2Fo': 'Retailer', 'cus_OYJ92MC8JOSHEX': 'Retailer', 'cus_OZlFJiT0RAOJox': 'Retailer', 'cus_P3RW0xU5xwr7IM': 'Retailer', 'cus_OYQxwN007gh1nD': 'Retailer', 'cus_OgYPTbxDBiZesE': 'Retailer', 'cus_OVTYEV0XeCh9Gi': 'Retailer', 'cus_OlUkA7GTld207r': 'Retailer', 'cus_OVMpnJHvh1uLyo': 'Retailer', 'cus_OSg92Nrv1laD03': 'Retailer', 'cus_Oioas7Y7HLERr2': 'Retailer', 'cus_RfdYdkOBEqCnH4': 'Retailer', 'cus_OxHvLFiMFcOAj0': 'Retailer', 'cus_OUz7ap0Rf6xhvx': 'Retailer', 'cus_OT35SyVaPA0ju5': 'Retailer', 'cus_OQb1Ec6epqZAd0': 'Retailer', 'cus_OUb292nvjcV7ji': 'Retailer', 'cus_Q3yzes0PEHn0zT': 'Retailer', 'cus_OQ7o01OAutu23g': 'Retailer', 'cus_P2mS88hKkNxKZY': 'Retailer', 'cus_PbGQkw3kD6A9N4': 'Retailer', 'cus_QfPND0KdNjMpXO': 'Retailer', 'cus_OdCY4w2FFacpD6': 'Retailer', 'cus_PtozUZloKDAwf1': 'Retailer', 'cus_ONVaKXk6VTqGxs': 'Retailer', 'cus_OLYKgDktaCCx5l': 'Ecommerce', 'cus_ONOPOiWbMotpin': 'Retailer', 'cus_OPkrVccsjboU9D': 'Retailer', 'cus_OPGbWPZn69UTMJ': 'Retailer', 'cus_ObOjipFLJr5mq7': 'Retailer', 'cus_OfTM8FCkKJYrRS': 'Retailer', 'cus_Oe0E0ql6GEv1sF': 'Retailer', 'cus_PBUN7UPi6Hf4Ct': 'Retailer', 'cus_OIYzoyMGKgP4c4': 'Retailer', 'cus_OHa6aSDuI3lP4E': 'Retailer', 'cus_OIFc1yJvV9i2hh': 'Ecommerce', 'cus_OJ4IofHs8d2C28': 'Retailer', 'cus_OD1gwmZ033hcYf': 'Retailer', 'cus_OC8HREyD6ArVZl': 'Retailer', 'cus_OA3sKAfzYW49SY': 'Retailer', 'cus_PLlSiCOLoSNXcg': 'Retailer', 'cus_Q4QhnThsxQ3Bp4': 'Retailer', 'cus_OQ4rbqWSwbvAC1': 'Retailer', 'cus_OkdsNAwGutIq3G': 'Retailer', 'cus_O7lVURFh30lkbP': 'Retailer', 'cus_O85Swo7NmYMgcR': 'Retailer', 'cus_O5ruZvkoz8TmOQ': 'Retailer', 'cus_O7kaFsuC5Qr4wu': 'Retailer', 'cus_OOHpk1MQ017Xjo': 'Retailer', 'cus_OYQB8YIHcnHK7L': 'Retailer', 'cus_PVXL8CoIFNmLOR': 'Retailer', 'cus_Q9e6KJMrMdod16': 'Retailer', 'cus_O4KtdccKpishEr': 'Retailer', 'cus_OCdTpehTTa0pcr': 'Retailer', 'cus_O3Gv2PNmOijhi2': 'Retailer', 'cus_O2CtGDRupgf1ZL': 'Retailer', 'cus_Ok4ThSEEz3cl5L': 'Retailer', 'cus_O7ow056XWrhz8C': 'Retailer', 'cus_OQ5VXTvCDY7wqT': 'Retailer', 'cus_O4MDCcCjQA3EaB': 'Retailer', 'cus_O0J5kjSjFetSWz': 'Retailer', 'cus_O227jG4u2zJmt7': 'Manufacturer', 'cus_OPn5Fi4drNtYMb': 'Retailer', 'cus_O9eJxZu5slnXBL': 'Retailer', 'cus_OII99zHZRwKppI': 'Retailer', 'cus_O4kVygSI3ErZQJ': 'Retailer', 'cus_O2usefij8zoAxc': 'Retailer', 'cus_O8kmlu4spr19Zt': 'Manufacturer', 'cus_QJDoSLpPWwSH0d': 'Retailer', 'cus_O9g3OTHfudMvYq': 'Retailer', 'cus_PZL2ZDrhy10imL': 'Retailer', 'cus_OCEZ8K7H7USEkq': 'Retailer', 'cus_NzvUZ9MaoPUVgs': 'Retailer', 'cus_NxcNr68GVuVPuc': 'Retailer', 'cus_LiwSLmU8WZZEI9': 'Manufacturer', 'cus_PaknlpBsWuEJas': 'Retailer', 'cus_Nq3hUjDknq65z6': 'Retailer', 'cus_O0fvDTRa8rqQzM': 'Retailer', 'cus_OupEoXgGaIanwq': 'Distributor', 'cus_NnW95GFzWgo4SR': 'Retailer', 'cus_Nm3eHD2xqAR2Nr': 'Retailer', 'cus_Nm4WNI686GZ6qZ': 'Retailer', 'cus_Oxo5kbtQIIkjk8': 'Retailer', 'cus_NknCjESalUA0jH': 'Distributor', 'cus_OYQZco1CojkJtc': 'Retailer', 'cus_NjPoPwWjz3IoUy': 'Retailer', 'cus_NlkXFrlS1gr2VF': 'Retailer', 'cus_NhWX6zrOr3FMYR': 'Retailer', 'cus_NhVMa9rSMXSNZm': 'Retailer', 'cus_NjGrf43QlVVXVa': 'Retailer', 'cus_NrFhk20V5vrcAw': 'Manufacturer', 'cus_NfbQrBomTZViR3': 'Retailer', 'cus_Nid0sz7OnLsRea': 'Retailer', 'cus_NkE2RlCod6GrMa': 'Retailer', 'cus_QU8ktiZGFwnyWu': 'Retailer', 'cus_N952NvGT7NidUp': 'Retailer', 'cus_OYmsf2AlrOBGvj': 'Retailer', 'cus_Ne9TPyXbaSCB3S': 'Retailer', 'cus_NbyIYq7CJW59XV': 'Retailer', 'cus_O5ZspF6ND9XVq6': 'Distributor', 'cus_Nf93HuqAADINA1': 'Distributor', 'cus_NcfodqimH9iSPg': 'Retailer', 'cus_L6dwMut4BYQN7d': 'Manufacturer', 'cus_NZLEvim9FcIbzv': 'Retailer', 'cus_NXOoeaxWhGdt4Z': 'Retailer', 'cus_NWHEWbzrmAg76d': 'Retailer', 'cus_OOEJNn4RjKGnuF': 'Retailer', 'cus_NRV4UULD1w7vAY': 'Retailer', 'cus_QE5rPSBiMUk9Sm': 'Retailer', 'cus_OYJ6Jl3PgUmz7x': 'Ecommerce', 'cus_NPaawpaiQMlifz': 'Retailer', 'cus_NSVW0cjrGxFcxR': 'Retailer', 'cus_QaCYxaZcneOTWo': 'Retailer', 'cus_O2a2U9v0b0MLlP': 'Distributor', 'cus_Oners4w79VQJLJ': 'Retailer', 'cus_OW869SFzsZ2KAl': 'Retailer', 'cus_Nhuu97bEq4RD60': 'Manufacturer', 'cus_O2XcSyEwn76Qbs': 'Retailer', 'cus_O4OS7jaKGPpztI': 'Retailer', 'cus_Nud1zgy3zPJmfn': 'Retailer', 'cus_Or2jIIDcTU3vHM': 'Retailer', 'cus_NmS8sAUsAB7XHQ': 'Retailer', 'cus_POcoLuWcY40qq7': 'Retailer', 'cus_P8m4uYmUd5d0iZ': 'Retailer', 'cus_RcWOHIqLzJAKU5': 'Retailer', 'cus_Okrh3filtngP34': 'Manufacturer', 'cus_NKM8hYnSBZQ9dj': 'Retailer', 'cus_Q7pPCJCuvz8Pp1': 'Retailer', 'cus_PSrJ9gGxnRx7Rj': 'Retailer', 'cus_NJGSbpZzDO1wPj': 'Retailer', 'cus_OVeV6vBUvcL2F6': 'Retailer', 'cus_NJ9tl5YXi41CaZ': 'Retailer', 'cus_Q9k2kAzBL58MmT': 'Retailer', 'cus_Nd2n7Cl0f916KF': 'Ecommerce', 'cus_NHg6rTv3Oc4ZwU': 'Retailer', 'cus_NGvLdijr3EfTml': 'Retailer', 'cus_O58CkuImjKP8yp': 'Ecommerce', 'cus_QX3o63nQGtnE7B': 'Retailer', 'cus_OFWqcOJVCPH8zn': 'Retailer', 'cus_OfKG6dYgbfcn2o': 'Ecommerce', 'cus_PrMf8ntC8Spm4P': 'Retailer', 'cus_PeM3WNejj6XQRK': 'Retailer', 'cus_OZzeFO63VtOYPx': 'Ecommerce', 'cus_OVoyc62YkUkb1h': 'Ecommerce', 'cus_OxoBAHZIwu3XJH': 'Retailer', 'cus_PR8XqTed9T0XnK': 'Manufacturer', 'cus_OLEeieV8zJduZr': 'Retailer', 'cus_NILQAJL2L4dCM8': 'Retailer', 'cus_NjKvu88UBmCWaC': 'Retailer', 'cus_NM1odXb2BbzFxe': 'Manufacturer', 'cus_Nfcu6h45TJ9ixt': 'Retailer', 'cus_NDvn5wbbGRkF6J': 'Retailer', 'cus_NBRd4k4TkAm1xr': 'Retailer', 'cus_N7TpRu6opNsToy': 'Retailer', 'cus_NPURhPcrPE8Ut5': 'Retailer', 'cus_NTxU80MxcvpRIz': 'Retailer', 'cus_LPr7kgbxeYlzuK': 'Retailer', 'cus_NeoxYgm7dMRlUb': 'Retailer', 'cus_NBzWwUBxrNzv1T': 'Retailer', 'cus_NJDpxLnMpdrhE4': 'Manufacturer', 'cus_P17hHoBGOywp4T': 'Ecommerce', 'cus_N8yzpLbFyIraBw': 'Retailer', 'cus_OQsbsWlpAOjP5V': 'Retailer', 'cus_N7c3mpCGJSAooB': 'Retailer', 'cus_N7agxSXmNK58pT': 'Retailer', 'cus_NmJz3allPkos6P': 'Ecommerce', 'cus_MxA4LXwvWQAyqy': 'Retailer', 'cus_PVpRccpQE6jfLh': 'Retailer', 'cus_NbSD3KXlatRfrb': 'Ecommerce', 'cus_RD5eOvxXeVuJFt': 'Ecommerce', 'cus_OVIPWWXO118riS': 'Retailer', 'cus_OSYctZLAZAimrG': 'Retailer', 'cus_N1DDYPMw9rYZRT': 'Retailer', 'cus_PddWfmbPVsAv1d': 'Retailer', 'cus_MyFb1YTpomk8ma': 'Retailer', 'cus_NEdyyhZRm31rmP': 'Ecommerce', 'cus_P05KQZNNmDuqqE': 'Retailer', 'cus_N2CAy0TO19aNVJ': 'Ecommerce', 'cus_PLLH16kGF6qJ9q': 'Retailer', 'cus_Oo2cFaM8mcT6wO': 'Retailer', 'cus_Mx5SKGTJQYtJrF': 'Retailer', 'cus_Mw3E8ycgvvdam4': 'Retailer', 'cus_MvjwnYsJwYXW7b': 'Retailer', 'cus_Pj2T26tVECdnop': 'Ecommerce', 'cus_OkM24zkx8iMViK': 'Retailer', 'cus_N2L2uWODcuqtyB': 'Retailer', 'cus_Njli9qG481TiBt': 'Retailer', 'cus_N8hTp3vybfAtPF': 'Manufacturer', 'cus_OlVjAT6fTyKbBS': 'Ecommerce', 'cus_MpED5yZqYCLoKS': 'Retailer', 'cus_Nd61ryjRMKp9tB': 'Retailer', 'cus_QtMpIYLU0sgkQ9': 'Retailer', 'cus_OdD7XNOyFpgUQp': 'Retailer', 'cus_NfziFfwL04A9XH': 'Retailer', 'cus_OZoj4reQMnJluS': 'Retailer', 'cus_Nbv2jS7tWszMsb': 'Retailer', 'cus_OmxezqQ7ChqDdE': 'Retailer', 'cus_NmO3RfksurTtdc': 'Retailer', 'cus_Oingjo4H9MkJlR': 'Retailer', 'cus_NkwlIJqiLF9idY': 'Retailer', 'cus_Pas6ZnYHUvpsXG': 'Retailer', 'cus_Nd14ryZluJ06AI': 'Retailer', 'cus_OTXP5teuaKw2AS': 'Retailer', 'cus_P0l8xYv0VFV3ZN': 'Retailer', 'cus_O3CD1aDFOAuvZe': 'Retailer', 'cus_Ra3YoLIyWf9flW': 'Retailer', 'cus_Ov9p1w2woqS0ZC': 'Retailer', 'cus_RbRFjDFsTX011L': 'Retailer', 'cus_PicYypDLUtoqff': 'Retailer', 'cus_NWO7z61no9XUzh': 'Retailer', 'cus_OsaKlDdiCOQcXu': 'Retailer', 'cus_O4NlCqIC6mv256': 'Retailer', 'cus_MoSQGxevJCuIX8': 'Ecommerce', 'cus_OgBS0eEpN8yIpl': 'Retailer', 'cus_ODPEF8mJOlbueE': 'Retailer', 'cus_NnZ2icAi1PmkiR': 'Retailer', 'cus_NsRTqkPZYUPhn7': 'Retailer', 'cus_NnUlF556XrIcVK': 'Retailer', 'cus_N9t7pcLBXsvvvP': 'Retailer', 'cus_Q6Hy6ZiyZjAkqc': 'Retailer', 'cus_NWchYRkG3Oy9BW': 'Retailer', 'cus_OcdRz1bhmI4yml': 'Ecommerce', 'cus_MmaCPTWUElkR8k': 'Retailer', 'cus_Mnl7m54USyhF5Y': 'Retailer', 'cus_MmZDSwSQDdrh4Z': 'Retailer', 'cus_Nx5JMV6x3t1WXQ': 'Manufacturer', 'cus_NXnNHPM16MHI9s': 'Ecommerce', 'cus_OckCP940RXIRto': 'Ecommerce', 'cus_S8Szrr2zwxpsvN': 'Ecommerce', 'cus_MhHX2zgAMvN97I': 'Distributor', 'cus_OGKQTDzVOqBqYS': 'Retailer', 'cus_PanJNcaiDgSpyf': 'Retailer', 'cus_NjSIQ5EicRTlPr': 'Retailer', 'cus_NnDpfsrvfao5T0': 'Retailer', 'cus_NUmiK9jyPsJiYr': 'Retailer', 'cus_OSlhqHADN7qJJG': 'Retailer', 'cus_OwJbV4U2jQsg7P': 'Manufacturer', 'cus_OEtunZL5pX44qG': 'Retailer', 'cus_NXprPFi1G79u5O': 'Retailer', 'cus_NzrDUzTN3C6eeU': 'Manufacturer', 'cus_GgOQU3bv3bz68U': 'Retailer', 'cus_NcsJbjG9Z8PRMq': 'Manufacturer', 'cus_ONRe7DZvcsC0nd': 'Retailer', 'cus_MTuYhiqa3PFL36': 'Retailer', 'cus_MpART3PsS1DO9r': 'Retailer', 'cus_OfSC55UxfvzskU': 'Ecommerce', 'cus_RWIc6Wyw08Rx6K': 'Manufacturer', 'cus_NpnAw50YhqKgii': 'Ecommerce', 'cus_NJaP1rUkMkloBM': 'Ecommerce', 'cus_MlozpBdEnGSgTC': 'Retailer', 'cus_O8UGubNWHnbhl0': 'Retailer', 'cus_Md5IuioXdhMpAo': 'Retailer', 'cus_NABb3asKAIKsbZ': 'Manufacturer', 'cus_MgXoPGqVyY5C5B': 'Manufacturer', 'cus_QFCFPWzoYwjB8i': 'Retailer', 'cus_OANeb5L6NyqTQc': 'Retailer', 'cus_O2z1kqF5ZXoezg': 'Retailer', 'cus_O7ntXrJnrhw4j4': 'Retailer', 'cus_O4SGwRkEj9rWJP': 'Retailer', 'cus_Tcy9gLL8hJrNXe': 'Retailer', 'cus_MlSjSLuXFyAau4': 'Retailer', 'cus_NWc2hroDY1fhVo': 'Retailer', 'cus_Q268ZKC4SsLvbC': 'Retailer', 'cus_OIEh1N0cqQEjTr': 'Retailer', 'cus_LD52dfOx5U0bRb': 'Retailer', 'cus_MfpneDO2SgTUti': 'Manufacturer', 'cus_MdR57viSltJ2dw': 'Retailer', 'cus_MwFrDEIhn9DKXF': 'Ecommerce', 'cus_MdBDF1pMAqcchu': 'Ecommerce', 'cus_N0t56fTZZYfZIi': 'Manufacturer', 'cus_IROggC8XcgWNpI': 'Retailer', 'cus_MEYFMK7M3MK6BC': 'Retailer', 'cus_MeOP6OrJbac8X9': 'Manufacturer', 'cus_L4rAackGWMSbob': 'Retailer', 'cus_MB8MiNweRz5yVT': 'Retailer', 'cus_PQcoW6DMkMFohA': 'Retailer', 'cus_MLGrUtPVlHmUQr': 'Retailer', 'cus_MOuGF9xRFbpqZ3': 'Retailer', 'cus_PdniTsZY389TJh': 'Manufacturer', 'cus_MYNtI6JVYrYtPR': 'Retailer', 'cus_MG5yEv7niWOEyw': 'Retailer', 'cus_MDgjzk12mChBDY': 'Manufacturer', 'cus_MaacklophBxkEL': 'Ecommerce', 'cus_M3KChprzRlrFej': 'Manufacturer', 'cus_M5wXcYfkbBcstE': 'Retailer', 'cus_LnSlOtUFXMKUAm': 'Retailer', 'cus_PUBqnorvtXJdfD': 'Retailer', 'cus_MsxtyQyLz2LLPb': 'Manufacturer', 'cus_M0ZroyhacVWzmL': 'Retailer', 'cus_LyWobjHJQPjvxV': 'Retailer', 'cus_MQW84Glg4yXB3a': 'Retailer', 'cus_M8rvwJTaWQZwbj': 'Retailer', 'cus_MjzfQRXu4UoEc3': 'Retailer', 'cus_NS4sj8FKUjew13': 'Ecommerce', 'cus_LxYqNcGdQOLlxM': 'Retailer', 'cus_MH28OorHuphdfU': 'Ecommerce', 'cus_R5cisYiJ6bmlq7': 'Ecommerce', 'cus_MI7FEyg0ytvvqR': 'Retailer', 'cus_MqdKgAFAltwnMn': 'Distributor', 'cus_LpPIezk9X2NX7M': 'Retailer', 'cus_LpcuLm9gdA6xZA': 'Ecommerce', 'cus_KU9SFd7vsidNPs': 'Retailer', 'cus_Mrm36AdwdvMwJI': 'Manufacturer', 'cus_PbA8xTanCOELX5': 'Retailer', 'cus_OSZQFGaiD7Klzt': 'Retailer', 'cus_Ofv0yYYuuxARhy': 'Retailer', 'cus_MqPCMzLljz6Xzg': 'Retailer', 'cus_NF873MShwDrjna': 'Retailer', 'cus_QgxVwc078dZXLJ': 'Retailer', 'cus_MQs3bU47rFNOOP': 'Retailer', 'cus_SAcq1NLNB0q5sM': 'Retailer', 'cus_OG3BBDvlb7E5uH': 'Retailer', 'cus_NPb3ONv66QDRHa': 'Retailer', 'cus_Mo66UpGAmueUPO': 'Retailer', 'cus_PNzlER3IjPYoLF': 'Manufacturer', 'cus_QTqoAWgEr52suC': 'Retailer', 'cus_MgzwHZyHe7VHxP': 'Retailer', 'cus_QfmRnDjoE7qOIq': 'Retailer', 'cus_M3f6uf7aTx3eWs': 'Retailer', 'cus_OXWbgakZzd1T2m': 'Retailer', 'cus_OKSu2GmzgqSH3N': 'Retailer', 'cus_NdpvXhRrm1lBFd': 'Retailer', 'cus_KWqiJpqYFz6AFT': 'Retailer', 'cus_MycnGcGnTOIbHu': 'Retailer', 'cus_NSiY348j8VTLgq': 'Retailer', 'cus_LpffCtIfQCNIHB': 'Ecommerce', 'cus_PDUcpIDcUOFleB': 'Ecommerce', 'cus_MoNiCGGX0NRFku': 'Retailer', 'cus_Lq2BE5VVWWmY0P': 'Ecommerce', 'cus_M7pteupO5LpC2I': 'Ecommerce', 'cus_LrsYRVNWMYvu8F': 'Manufacturer', 'cus_Lmz6zqaFo5ezO4': 'Ecommerce', 'cus_Mspb1DhYTwaUkr': 'Ecommerce', 'cus_M7gQiUe5dTo45q': 'Retailer', 'cus_MEUynVjBknYL2E': 'Ecommerce', 'cus_OJuabZlPB2E0eS': 'Retailer', 'cus_HX36vH6ucACadJ': 'Retailer', 'cus_Ljz1TVIYS0YGyq': 'Ecommerce', 'cus_LaHbskplDfInRC': 'Ecommerce', 'cus_SdTSTPL9gYtQsr': 'Retailer', 'cus_MqKuFXrRBNZ6vR': 'Ecommerce', 'cus_LUeF6vg76Wo5hF': 'Ecommerce', 'cus_P8V8rEHHVwVa3x': 'Retailer', 'cus_ONJOV2ldtcu4E9': 'Manufacturer', 'cus_Oex5dStiSQ82lE': 'Manufacturer', 'cus_Sm3yAIjS7Fwh2Y': 'Retailer', 'cus_PjVA8nzs0CzfVs': 'Ecommerce', 'cus_Kf3rTMgEvRPthe': 'Ecommerce', 'cus_OntY6HSqDZonmi': 'Manufacturer', 'cus_QjNU3gsjPwg9EU': 'Manufacturer', 'cus_P828zfL61glopg': 'Manufacturer', 'cus_LpIZkopsoE3nA0': 'Retailer', 'cus_LSCvVmVh8BfNe4': 'Retailer', 'cus_LcidSBayCIOV2o': 'Distributor', 'cus_LRm83wHu93z9Er': 'Retailer', 'cus_LJtjg50AlFiy8O': 'Manufacturer', 'cus_M9BJjM0CROWcUj': 'Manufacturer', 'cus_O0FchOpu5PBjYS': 'Ecommerce', 'cus_L4SKRsp7GPzlnJ': 'Manufacturer', 'cus_LP839IaX8p9X9e': 'Retailer', 'cus_M56jA2UUZBUkIJ': 'Retailer', 'cus_LP2Ezl812N04m2': 'Manufacturer', 'cus_LKv4OsFtsFRhkP': 'Manufacturer', 'cus_QWjYCK12aUNn0n': 'Ecommerce', 'cus_LIKIEdXTauZVhj': 'Retailer', 'cus_LJqfemH25sHGsQ': 'Retailer', 'cus_LQHsuN7HwhLm29': 'Manufacturer', 'cus_NtseHe80BISocW': 'Manufacturer', 'cus_LDcqY0UV93cZLr': 'Retailer', 'cus_PvqrpPh4babnip': 'Retailer', 'cus_LPmG2hFhTSAjIc': 'Ecommerce', 'cus_LC0zGPGdwh0ioC': 'Distributor', 'cus_LCp3jjxjvb9WeI': 'Retailer', 'cus_LATroapk21IvBt': 'Retailer', 'cus_LSSutc26uHZmNp': 'Retailer', 'cus_LFMtsoC8uFOKTU': 'Retailer', 'cus_LI5gXUU7aSuw9o': 'Retailer', 'cus_M2vERZQHh1jdg6': 'Retailer', 'cus_LMqY6fRxfTIw6H': 'Retailer', 'cus_P1UJ3Qb0OkuFLU': 'Retailer', 'cus_NwWBw4Z5sfdi1e': 'Ecommerce', 'cus_LAZbq1HnxHQlNm': 'Retailer', 'cus_K1luqLsm67O5HV': 'Retailer', 'cus_LSUZYVTod7Rk1v': 'Retailer', 'cus_OaDWV9VMxqdoJv': 'Retailer', 'cus_MZ8Y5zeJGhREs4': 'Retailer', 'cus_LKCyErqqQ9VHoq': 'Retailer', 'cus_LVASMYZcXPGDYO': 'Retailer', 'cus_MBRJe6Wt5YfoGa': 'Retailer', 'cus_MM0r0T6ngTnCfB': 'Retailer', 'cus_HmlUsuzmu5RvKl': 'Ecommerce', 'cus_L2vROfDAfrLBEQ': 'Manufacturer', 'cus_L5PwWscq0xZNV0': 'Retailer', 'cus_L7AjN76kMHMGGG': 'Manufacturer', 'cus_L2H2YDZtRCrnKU': 'Retailer', 'cus_Kgaj6EaUlp0af0': 'Retailer', 'cus_LFn2FiZ7AKmZLe': 'Retailer', 'cus_MDMzWieI2yWNNL': 'Retailer', 'cus_MTo9OaB8PFbK1S': 'Retailer', 'cus_MW9rzYVNKmwIiS': 'Distributor', 'cus_NMwaNWqvuAVP67': 'Retailer', 'cus_OUdYKCtL9tOHIA': 'Ecommerce', 'cus_LQD0BVVXcA5O4L': 'Retailer', 'cus_MMN0gcLdbjS8Jj': 'Ecommerce', 'cus_ODHZbHZWa58xcH': 'Retailer', 'cus_MmEiO9fk5eLQvP': 'Retailer', 'cus_Ku4vlcTohixATb': 'Retailer', 'cus_KnGnzRIHpAdFSi': 'Retailer', 'cus_KmTSAVDG1PXait': 'Ecommerce', 'cus_Ktho8OBAUXRLcH': 'Distributor', 'cus_LPtlVuQNwPB2TH': 'Retailer', 'cus_M83fZ4NheTRv8W': 'Retailer', 'cus_KkNAoiboVbWucL': 'Retailer', 'cus_KmqBgx62cu55rd': 'Manufacturer', 'cus_LfdNBprJiTBZVW': 'Retailer', 'cus_Myt26baNbQIEY5': 'Ecommerce', 'cus_Rd0bj3WpA2g3Kv': 'Retailer', 'cus_KUCTC7GW3r1TLp': 'Retailer', 'cus_KkyLV9XdNspdfK': 'Manufacturer', 'cus_LIS8wJmgxcp9A3': 'Manufacturer', 'cus_KeK1ABsH4gjEZQ': 'Retailer', 'cus_KeIJOfwnMTBMZL': 'Retailer', 'cus_LkUFKJXHl6Ptfg': 'Retailer', 'cus_Lap9W2FEI2zjZu': 'Retailer', 'cus_KOXZF2maCA5lwx': 'Manufacturer', 'cus_LUOqwpFNv45iQz': 'Retailer', 'cus_KFAqOYmiHMwPW0': 'Manufacturer', 'cus_KcOKQ99Jzx7wba': 'Distributor', 'cus_Hs0fAslDTxmEqx': 'Retailer', 'cus_KlpsY693Ez0ym5': 'Retailer', 'cus_KZ5cWe1H4hFWjg': 'Retailer', 'cus_MYMQRST2yK4Wv4': 'Retailer', 'cus_ME4mfcp9dqSayo': 'Ecommerce', 'cus_KWp8qN3IYtULYD': 'Retailer', 'cus_O1lbW1EwO6QRJm': 'Retailer', 'cus_R0NlR9fzFbrqK4': 'Retailer', 'cus_KXAq17Mg9vcqbw': 'Retailer', 'cus_Kgv0rsImf8Stfj': 'Retailer', 'cus_P6kZBjcala0J8r': 'Manufacturer', 'cus_LH8WS4mEoOCZ6O': 'Manufacturer', 'cus_Mtf5PSbFb5cL4B': 'Retailer', 'cus_LNzALSHIT6oQBY': 'Retailer', 'cus_QiCPUgo28dYuZg': 'Retailer', 'cus_LPFwny8tmKa44U': 'Manufacturer', 'cus_KRYngiyhrigumT': 'Retailer', 'cus_KSKZs6STLSfZsE': 'Retailer', 'cus_MthDVAcsdW5BWh': 'Ecommerce', 'cus_OcHUGdAXltnWJl': 'Ecommerce', 'cus_OxKoMRFOmcpQip': 'Ecommerce', 'cus_OpbRd8lETi3eAV': 'Manufacturer', 'cus_MR4Jzh34vwpAl1': 'Ecommerce', 'cus_MKsS6LuvOG1lWs': 'Manufacturer', 'cus_OuvOHhnMs4flYQ': 'Manufacturer', 'cus_KVBzinagDi8HKr': 'Manufacturer', 'cus_OTF4t16uqmqV35': 'Manufacturer', 'cus_NyzH1EgfDZrqIm': 'Ecommerce', 'cus_Lw4C0mMr4owjtp': 'Retailer', 'cus_NONICXjVwOLVjA': 'Ecommerce', 'cus_KKGaICmWxbL7rc': 'Ecommerce', 'cus_M0EiQxMdJOUmU4': 'Ecommerce', 'cus_Mt9MCR6EGRb0vO': 'Ecommerce', 'cus_SIe3xVBo8lWdEh': 'Ecommerce', 'cus_KTQwWXgRh6x8zh': 'Manufacturer', 'cus_KTonA8VSNOVl3W': 'Manufacturer', 'cus_KUszo4wrSPH1Yh': 'Retailer', 'cus_KRYtc2BJFnvYz4': 'Retailer', 'cus_KQnXhN8nqD63Or': 'Retailer', 'cus_KmTGvVTpf88ABk': 'Retailer', 'cus_QUUppBVqwzWXUs': 'Manufacturer', 'cus_M2LyoOPgYtJvIg': 'Manufacturer', 'cus_KJD7kZ52hLGkqw': 'Manufacturer', 'cus_KbDltkubUOKLaK': 'Ecommerce', 'cus_KBl0vuvTLfTaZD': 'Ecommerce', 'cus_JrV8kcBW8lTumv': 'Ecommerce', 'cus_JKzZn6FYaPM4Kg': 'Retailer', 'cus_Jio2qIseFEUY3b': 'Ecommerce', 'cus_JR0JS0vPqEQMD8': 'Retailer', 'cus_IkdWo9NJ5heCVX': 'Manufacturer', 'cus_ItCHqfJve2L5pJ': 'Manufacturer', 'cus_JqnQPN0ElneInq': 'Retailer', 'cus_I7nKbkKbV3uGlC': 'Manufacturer', 'cus_JKvjSC42j8SHAZ': 'Ecommerce', 'cus_MKqR3UneIcQmAy': 'Distributor', 'cus_JgBlcVL72zGSCU': 'Ecommerce', 'cus_IPjCpDfcJsf1H5': 'Retailer', 'cus_MfuFchFwSm1Axx': 'Ecommerce', 'cus_JNiNAQwja2rXKN': 'Retailer', 'cus_MQ7SaCHUokCGnc': 'Retailer', 'cus_Jb9tbNvJQ5RIbq': 'Distributor', 'cus_JM8z5hE3PVtL11': 'Ecommerce', 'cus_JKZKTxuv7563sR': 'Manufacturer', 'cus_HbUoXdWoSqNy5a': 'Distributor', 'cus_LhyXNN2A6Z56EJ': 'Retailer', 'cus_KEafqLowWHvhZC': 'Retailer', 'cus_JCtM4HAusFNm1i': 'Retailer', 'cus_JaMk38R9WdJBMi': 'Ecommerce', 'cus_JauAUBfNNtuPs1': 'Ecommerce', 'cus_JY5VHIQSO4g6Uk': 'Retailer', 'cus_Ki91r3Up8P0JWR': 'Retailer', 'cus_Il4KLE1wxdy6m2': 'Retailer', 'cus_Jw2NQjdEUXh7j6': 'Ecommerce', 'cus_JVXhzkvXtjrahD': 'Ecommerce', 'cus_KBUj0FT0NE8h42': 'Retailer', 'cus_JOLngcWfQOiObk': 'Retailer', 'cus_Je7XCmgNuuASgu': 'Retailer', 'cus_JggFEUkQFaERs6': 'Manufacturer', 'cus_Ir8xSrFB4gaHW9': 'Manufacturer', 'cus_KgvxRXwlKMZcnK': 'Manufacturer', 'cus_Hxc3uP7hHRgalz': 'Retailer', 'cus_KeECDdsjJFUYFL': 'Retailer', 'cus_IPbcwRPdTz27a9': 'Retailer', 'cus_JAwuzR7xcmMlWx': 'Manufacturer', 'cus_Ik0o3AOBg0664i': 'Manufacturer', 'cus_Ki9BxLbMTLQEse': 'Retailer', 'cus_LMQole8Y8EVZVU': 'Manufacturer', 'cus_JQGks8AB50thuE': 'Retailer', 'cus_JXit4B97L26b7y': 'Retailer', 'cus_K35AvjYx7RuakJ': 'Retailer', 'cus_Sx6aFDaMmSWkbt': 'Manufacturer', 'cus_JtPTUWEzKdFFXr': 'Ecommerce', 'cus_QMkelwbNVI1fKf': 'Ecommerce', 'cus_KuPHmBcHhPq3wJ': 'Retailer', 'cus_JtEjqY3vjWLsja': 'Ecommerce', 'cus_JVKvr1ZvZjinet': 'Manufacturer', 'cus_IaUMPS2Xl5XhdY': 'Manufacturer', 'cus_HbUnaZeK1phY0F': 'Retailer', 'cus_JW3rXDYEIbDCAO': 'Ecommerce', 'cus_Jutxlh4jepft3e': 'Retailer', 'cus_JawbHnlK9ZykF4': 'Ecommerce', 'cus_M67dsGNHvw81WX': 'Retailer', 'cus_MaoK7vePqYn1Yb': 'Manufacturer', 'cus_HbUgao41mGOf6H': 'Manufacturer', 'cus_JdBBZgkn2rQp7E': 'Retailer', 'cus_J8QFKaWOWKlm37': 'Manufacturer', 'cus_K9S5n2gf1jRYuu': 'Manufacturer', 'cus_K9k89ec4qJR5cK': 'Manufacturer', 'cus_KmVMPxLnZF5IXT': 'Retailer', 'cus_JGw4sGQSpSWe9e': 'Retailer', 'cus_J2hHnwGc8xvagv': 'Retailer', 'cus_K2A29HphP7bqf5': 'Manufacturer', 'cus_JshXShmpMsxvty': 'Retailer', 'cus_J3r5YscBFKKymd': 'Retailer', 'cus_IkFZmFbRudeitS': 'Ecommerce', 'cus_JL72BepMVPzj50': 'Distributor', 'cus_HbUnOEaU0fHzl6': 'Retailer', 'cus_KwBLRo2cE2z2kH': 'Manufacturer', 'cus_LHD9rBZWUSf1yH': 'Retailer', 'cus_PiwwG4vz5N45DA': 'Manufacturer', 'cus_JLJlrsTC15oNRV': 'Retailer', 'cus_J5fx1Ahh6Cr3xM': 'Ecommerce', 'cus_Jg9kC5pZ4tjrEU': 'Ecommerce', 'cus_JJ6bwKnwZ2WvnX': 'Retailer', 'cus_J90TznPfrm7yRg': 'Distributor', 'cus_MoKxrRr4pbwDwZ': 'Manufacturer', 'cus_JO0gYrH0ikxBLR': 'Retailer', 'cus_HbUnuhSgGBSPRl': 'Manufacturer', 'cus_JNNjYV14x832og': 'Retailer', 'cus_Jl8wBAY5n1uNYw': 'Manufacturer', 'cus_IahE95QOQa2Qq1': 'Manufacturer', 'cus_KQipOPbsHlRRoH': 'Retailer', 'cus_JLJHZUfG54nFlq': 'Manufacturer', 'cus_Mp818Ui9CVCovk': 'Distributor', 'cus_JTl2ii4t4QX1oj': 'Ecommerce', 'cus_HzSTAr3Qaug5eQ': 'Manufacturer', 'cus_HbUnjYfovVva2w': 'Ecommerce', 'cus_O7vsP2vwfvznmR': 'Retailer', 'cus_HbUnZ7PFmXtswe': 'Manufacturer'}
_HS_TYPE_BY_EMAIL = {'joni@thefloordesignstudio.co.uk': 'Retailer', 'cremonese@outlook.com': 'Manufacturer', 'wiame@unamourdetapis.com': 'Retailer', 'derrick@elevatecleaning.cc': 'Retailer', 'paul@safescapes.com': 'Retailer', 'support@tristategaragefloors.com': 'Retailer', 'mkgrove27@gmail.com': 'Retailer', 'hello@safetymat.com': 'Manufacturer', 'otavio@cdmcorp.es': 'Retailer', 'alex@scicoatings.com': 'Distributor', 'admin@lifetimecoatingsllc.com': 'Retailer', 'fortressfloorsofmn@gmail.com': 'Retailer', 'aron@poxymon.com': 'Retailer', 'alexj@emonster.ca': 'Ecommerce', 'compralojadaceramica@outlook.com.br': 'Retailer', 'xionthrive@gmail.com': 'Retailer', '1garagerescue@gmail.com': 'Retailer', 'comercial@housemateriais.com': 'Retailer', 'mike2020armenia@gmail.com': 'Retailer', 'info@qualitypaintingofvirginia.com': 'Retailer', 'grow@letsgodigital.agency': 'Retailer', 'gatorepoxy@gmail.com': 'Retailer', 'david@dawsondelivery.com': 'Retailer', 'info@rugstarz.com': 'Ecommerce', 'compras03@construtayo.com.br': 'Retailer', 'josefina.cohenp@gmail.com': 'Retailer', 'simplyconstruction99@gmail.com': 'Retailer', 'connorschupbach@gmail.com': 'Retailer', 'dave@davesheavenlyhomes.com': 'Retailer', 'brandons@vanguardremodeling.com': 'Retailer', 'apexccwa@gmail.com': 'Retailer', 'joe@serenityconcretecoatings.com': 'Retailer', 'opusrenovation22@gmail.com': 'Retailer', 'durciribeiro@hotmail.com': 'Distributor', 'mike@crashofrhinospainting.com': 'Retailer', 'carlosmenezes.eng@outlook.com': 'Distributor', 'jake@concretecote.com': 'Retailer', 'sigepoxy@gmail.com': 'Retailer', 'solution.coatings@icloud.com': 'Retailer', 'sales@dryvway.com.au': 'Retailer', 'mkt@redeconstruutil.com.br': 'Retailer', 'fortressfloorsmi@gmail.com': 'Retailer', 'david@tristateepoxy.io': 'Retailer', 'billy@paintanddecorate.com.au': 'Retailer', 'abigail@double.online': 'Ecommerce', 'bmiller@acesstoneepoxy.com': 'Retailer', 'danielle.vieira@floori.io': 'Distributor', 'cbax77@hotmail.com': 'Retailer', 'admin@ecocreteadelaide.com.au': 'Retailer', 'corelgustavo@hotmail.com': 'Retailer', 'carmen@arabescoacabamentos.com.br': 'Distributor', 'stoneirvine01@gmail.com': 'Retailer', 'info@summitridgecoatings.com': 'Retailer', 'valdenir.luiz@construvip.com.br': 'Distributor', 'cristianomassaco@gmail.com': 'Retailer', 'accounting@apexcoatings.ca': 'Retailer', 'anyconcreteandepoxysolutions@outlook.com': 'Retailer', 'grant@pebblemix.com.au': 'Retailer', 'rafaporto_17@icloud.com': 'Retailer', 'nigel@melbournecarpettiles.com.au': 'Retailer', 'accounts@allcoastpainting.com.au': 'Retailer', 'the123plan@gmail.com': 'Retailer', 'lauren@pristinepaintinghawaii.com': 'Retailer', 'montecristomateriais@gmail.com': 'Retailer', 'info@granitestateepoxy.com': 'Retailer', 'meagan@missioncretecoatings.com': 'Retailer', 'neilson@asturiasmc.com.br': 'Distributor', 'varejaodopisoadm@gmail.com': 'Retailer', 'dcd0914@gmail.com': 'Retailer', 'miked@homeshieldcoating.com': 'Retailer', 'ccsepoxy@gmail.com': 'Retailer', 'admin@epoxyfloorsealers.com': 'Retailer', 'info@lowtidesupply.com': 'Distributor', 'info@showtimefloors.com': 'Retailer', 'permabrite.warranty@gmail.com': 'Retailer', 'douglas.chow@gmail.com': 'Retailer', 'irmaosnevesloja@gmail.com': 'Retailer', 'info@modifloors.com': 'Retailer', 'hamza@alphatimber.com.au': 'Retailer', 'rrusinski@swaydepoxy.com': 'Retailer', 'chirprofessionals@gmail.com': 'Retailer', 'rubberstonenw@gmail.com': 'Retailer', 'info@mr-epoxy.de': 'Retailer', 'insolador01@gmail.com': 'Retailer', 'solidcrete78@gmail.com': 'Retailer', 'kevins@sledgeepoxyworx.com': 'Retailer', 'dnordby50@gmail.com': 'Retailer', 'tony@elitegf.com': 'Retailer', 'amazacrete@gmail.com': 'Retailer', 'elitefloorsurfacing@gmail.com': 'Retailer', 'queirozpisoserestimentos@gmail.com': 'Retailer', 'jeffpeterson68@gmail.com': 'Retailer', 'brian@encoregroupnj.com': 'Retailer', 'chris@603epoxy.com': 'Retailer', 'graeme@corna2corna.co.za': 'Retailer', 'vitoravilasilverio@gmail.com': 'Retailer', 'theconcreteartisan@gmail.com': 'Retailer', 'chad@armorcoatingco.com': 'Retailer', 'sammyorozco.39@gmail.com': 'Retailer', 'david@foxycoatings.com': 'Retailer', 'contato@casaraotemdetudo.com.br': 'Retailer', 'tori@stoneset.com.au': 'Retailer', 'peteortiz831@gmail.com': 'Retailer', 'matt@brightstepcoatings.com': 'Retailer', 'info@elegantcoatings.ca': 'Retailer', 'marcio.pereira@marson.com.br': 'Retailer', 'demaybn@hotmail.com': 'Retailer', 'michelle@epoxywhse.com': 'Ecommerce', 'messiasmmf7@gmail.com': 'Retailer', 'murilo@comercialmontebelo.com': 'Retailer', 'angelsmatconstrucao@gmail.com': 'Retailer', 'diai.gaspar@hotmail.com': 'Retailer', 'silvasoares3020@hotmail.com': 'Retailer', 'creativegaragefloor@gmail.com': 'Retailer', 'info@adelaidecustomconcrete.com.au': 'Retailer', 'sidgraef@gmail.com': 'Retailer', 'mail@coatingbrothers.com': 'Retailer', 'ventas@mugla.mx': 'Ecommerce', 'jeremy@wasatchconcretecoatings.com': 'Retailer', 'sales@premiumflooringllc.com': 'Retailer', 'petri@madfloors.fi': 'Retailer', 'tmoralesjr1@gmail.com': 'Retailer', 'tim@epoxyfloorsnmore.com': 'Retailer', 'terryclement@hotmail.com': 'Retailer', 'aceepoxycoatings@gmail.com': 'Retailer', 'carolkeese@carolinaaircare.com': 'Retailer', 'johnny@southernimpacthomes.com': 'Retailer', 'tonematt@yahoo.com': 'Retailer', 'support@octoprowash.com': 'Retailer', 'trueellusions@gmail.com': 'Retailer', 'smithjowan504@yahoo.com': 'Retailer', 'garagecoatingtn@gmail.com': 'Retailer', 'michael@rhinocoatings.com': 'Retailer', 'shay@coatgoat302.com': 'Retailer', 'nboyce653@gmail.com': 'Retailer', 'jeffery0831@aol.com': 'Retailer', 'mario@valuepaintingandflooring.com': 'Retailer', 'info@regalcoatings.com': 'Retailer', 'aldo@bernardswoodfloors.com': 'Retailer', 'dpepoxy13@gmail.com': 'Retailer', 'goatedcoatings@gmail.com': 'Retailer', 'marcelo.aml@hotmail.com': 'Retailer', 'office@catalystcoatings.com': 'Retailer', 'ask@rrpil.com': 'Manufacturer', 'hsisk@thresholdbrands.com': 'Retailer', 'saqdcd@gmail.com': 'Retailer', 'tito@northeaststoneconcrete.com': 'Retailer', 'garagearmorct@yahoo.com': 'Retailer', 'tom@concretecoatingaustin.com': 'Retailer', 'hzargar@uh.sa': 'Manufacturer', 'stj@promal.dk': 'Retailer', 'rich@msmedia360.com': 'Retailer', 'tom@floorsinaday.com': 'Retailer', 'beth@calbearconst.com': 'Retailer', 'jeff@redfoxepoxy.com': 'Retailer', 'michael@surfaceology.com': 'Retailer', 'piotr@mat-tar.pl': 'Manufacturer', 'completeyourconcrete@yahoo.com': 'Retailer', 'isabela@radica.com.br': 'Retailer', 'createastonecoatings@gmail.com': 'Retailer', 'amy.groundfxflooring@gmail.com': 'Distributor', 'carlos@jcconcreterestorationinc.com': 'Retailer', 'rporesurfacing@mail.com': 'Retailer', 'miguel@bullsfloorcoatings.com': 'Retailer', 'awarner@mobau-wirtz-classen.de': 'Retailer', 'hello@tilesman.com': 'Distributor', 'dchacon24@live.com': 'Retailer', 'support@reachmrepoxy.com': 'Retailer', 'sales@rubberdecker.com': 'Retailer', 'keith@prosealnj.com': 'Retailer', 'wedoconcretecoatingsla@gmail.com': 'Retailer', 'con@deckandfence.com.au': 'Retailer', 'pisosyestampadosdebc@gmail.com': 'Manufacturer', 'derrick@rezfloor.com': 'Retailer', 'jordi@terracassa.com': 'Retailer', 'mason@shieldutah.com': 'Retailer', 'pearlepoxydesigns@gmail.com': 'Retailer', 'lilajakub1@gmail.com': 'Retailer', 'projectxconcrete@gmail.com': 'Retailer', 'goldenconcreteresurfacing@outlook.com': 'Retailer', 'dcsincomaha@gmail.com': 'Retailer', 'ben@b2bwoodproducts.co.uk': 'Distributor', 'marketing@bdagroup.co.id': 'Distributor', 'info@battlebornpainting.com': 'Retailer', 'suzuki-kei@tajima.co.jp': 'Manufacturer', 'miuvcoatedfloors@gmail.com': 'Retailer', 'bradleys@htechflooring.com': 'Retailer', 'jaydgaitin3@gmail.com': 'Retailer', 'centerpenha4@gmail.com': 'Retailer', 'danjillings@me.com': 'Retailer', 'paz.sanmillan@uniber.com.ar': 'Retailer', 'daniel.vazquez@nimat.com.ar': 'Ecommerce', 'info@snapperepoxy.com': 'Retailer', 'info@falconcoatings.com': 'Retailer', 'office@clearchoicecoatings.com': 'Retailer', 'kojo.danso@isonemusa.com': 'Distributor', 'laura@philadelphiaconcretefloor.com': 'Retailer', 'matt@ocsconcretesolutions.com': 'Retailer', 'info@davinciconcretecoatings.com': 'Manufacturer', 'info@twgaragepros.com': 'Retailer', 'sales@performancefloorsandcoating.com': 'Retailer', 'matt@solidconcretecoatings.com': 'Retailer', 'sean@bruceconcretecoatings.com': 'Retailer', 'walker@lowecofloors.com': 'Retailer', 'marcus@thejagangroup.com.au': 'Retailer', 'joe@volf.com.au': 'Retailer', 'lmeredith@rhinolinings.com.au': 'Retailer', 'lg@ausfloorworks.com.au': 'Manufacturer', 'ryan@coatingsden.com': 'Retailer', 'nick@trmroofing.com': 'Retailer', 'paintitright00@gmail.com': 'Retailer', 'david@spartancoat.com': 'Retailer', 'craig@americanpolyfloor.com': 'Retailer', 'jstnwlf928@gmail.com': 'Retailer', 'hello@agcnz.co.nz': 'Retailer', 'gerencia@bastetfloors.com': 'Ecommerce', 'artem.b555@gmail.com': 'Retailer', 'john@brilliantconcrete.com': 'Retailer', 'dobritoariel@gmail.com': 'Ecommerce', 'ori.elmalan@gmail.com': 'Retailer', 'stephen@bearfoot.ie': 'Retailer', 'contact@londonlinings.com.au': 'Ecommerce', 'ben@epoxyadelaide.com.au': 'Retailer', 'terry@tlcec.com.au': 'Retailer', 'tim@epoxyflooringco.com.au': 'Ecommerce', 'info@shimi.com.au': 'Ecommerce', 'alan@hardwooddistribution.com': 'Retailer', 'kimj@horizoncoatings.com.au': 'Manufacturer', 'quickresponsefloorcoatings@gmail.com': 'Retailer', 'ritu@floordecor.co.nz': 'Retailer', 'raulolavegutierrez@gmail.com': 'Retailer', 's.baz@artloop.com.tr': 'Manufacturer', 'unclekimsflooring@gmail.com': 'Retailer', 'info@evolveconcretecoating.com': 'Retailer', 'scott@dbackpainting.com': 'Retailer', 'omerhazer1@gmail.com': 'Retailer', 'info@duracoatfloors.com': 'Retailer', 'greyes@reinnovacion.com': 'Retailer', 'igor@floori.io': 'Retailer', 'invoices@bdurable.com': 'Retailer', 'americandreamspaces@gmail.com': 'Retailer', 'contact@solpex.ca': 'Manufacturer', 'administracion@biancohogar.com.ar': 'Ecommerce', 'sp@sphouseworld.ro': 'Retailer', 'alan@teamepoxy.com': 'Retailer', 'charlie@comercrossgarage.com': 'Retailer', 'colby@gatewayepoxy.com': 'Retailer', 'jmichelakis@lakiotis.gr': 'Ecommerce', 'david@concretecoatings-ga.com': 'Retailer', 'felipe@kocmat.com.ar': 'Retailer', 'quotes@laminatefloors.co.za': 'Ecommerce', 'mads@gulvxtra.no': 'Ecommerce', 'cl@jti-gulv.dk': 'Retailer', 'info@schmidtcoating.dk': 'Retailer', 'andrea@avalonflooringpros.com': 'Retailer', 'umisalmah1994@gmail.com': 'Retailer', 'mbflooring93@gmail.com': 'Retailer', 'service@baumwollputz-shop.de': 'Ecommerce', 'jromo@pisoflotantesantiago.cl': 'Retailer', 'g.beens@vloereninterieur.com': 'Ecommerce', 'contato@kamacho.com.br': 'Retailer', 'lenardo@fermatecferragens.com.br': 'Retailer', 'kimberly@fastlanecoatings.com': 'Retailer', 'proconcreteexpertsja@gmail.com': 'Retailer', 'kylecompletecoatings@gmail.com': 'Retailer', 'antonio.appolinario@polishop.com.br': 'Ecommerce', 'emersonhas2@gmail.com': 'Retailer', 'office@slgconcretecoatings.com': 'Retailer', 'ivette.deleon@nitropiso.com.mx': 'Retailer', 'mlrossello@rossello.com.pe': 'Manufacturer', 'juan@simplo.store': 'Ecommerce', 'info@durableiowa.com': 'Retailer', 'russ@acppaintingllc.com': 'Retailer', 'spartancoatingsfl@gmail.com': 'Retailer', 'ulises.gonzalez@premiergarage.com': 'Retailer', 'nam@zgdenver.com': 'Retailer', 'joe@lnsconcretecoatings.com': 'Retailer', 'franchise@thegaragefloorco.com': 'Retailer', 'tracy@premieroverlay.com': 'Retailer', 'marketing@marblelife.com': 'Retailer', 'vish@mach1epoxy.com': 'Retailer', 'layomi@vancouverepoxyflooring.ca': 'Retailer', 'tt@memphiscoatingscompany.com': 'Retailer', 'dalton@titanflooringapplications.com': 'Retailer', 'epoxytechhouston@gmail.com': 'Retailer', 'madisoncoatingscompany@gmail.com': 'Retailer', 'conceptcoatings1@gmail.com': 'Retailer', 'james@progaragerenovations.com': 'Retailer', 'cgsolutions407@outlook.com': 'Retailer', 'jimmymiller1@gmail.com': 'Retailer', 'lozanoclaudio4@gmail.com': 'Retailer', 'rich@garageflooringpros.com': 'Retailer', 'agcepoxy@gmail.com': 'Retailer', 'kyle@astaloslfc.com': 'Retailer', 'blacoy7@gmail.com': 'Ecommerce', 'renewfloorcoatings@gmail.com': 'Retailer', 'info@lsconcretecoatings.com': 'Retailer', 'info@cornerstonehsr.com': 'Retailer', 'chris.butler@gnugarage.com': 'Retailer', 'davef@yourgaragecave.com': 'Retailer', 'chris@capconcretecoatings.com': 'Retailer', 'nick@garagefloorcoating.com': 'Retailer', 'lee.blake@featureflooring.com': 'Retailer', 'leva@sydneyepoxyfloors.com.au': 'Ecommerce', 'office@bestbrospainting.com': 'Retailer', 'diamondshieldcoatings@gmail.com': 'Retailer', 'cs@loudbros.com': 'Retailer', 'w.marcinkowski@poli-eco.pl': 'Manufacturer', 'moi@nuespacios.com': 'Ecommerce', 'atheer@carrim.co.za': 'Ecommerce', 'gavin@eurobel.com.ph': 'Ecommerce', 'rexdou@rockyhardwoodinc.com': 'Distributor', 'jason@americanremodeling.net': 'Retailer', 'jason@msepoxy.com': 'Retailer', 'mix@coatingdesigns.com': 'Retailer', 'familycmultiservicesllc@gmail.com': 'Retailer', 'info@gounitedcoatings.com': 'Retailer', 'renofrank90@gmail.com': 'Retailer', 'swflsales@concretecraft.com': 'Manufacturer', 'sgarcia@nanotech-epoxy.com': 'Retailer', 'info@dreamcretecc.com': 'Retailer', 'hello@blackrhinogaragefloors.com': 'Manufacturer', 'tim@randswoodflooring.com': 'Retailer', 'chowdhury.prasun@hrjohnsonindia.com': 'Manufacturer', 'revesthousebrasil@gmail.com': 'Retailer', 'cliff@curbappealprofessionals.com': 'Retailer', 'gtorres@decorcenter.pe': 'Retailer', 'prearte@tucson.com.ar': 'Ecommerce', 'mvarela@cerronegro.com.ar': 'Manufacturer', 'emanuelnoriega@edificor.com.ar': 'Ecommerce', 'kimberly.gonzalez@castel.com.mx': 'Ecommerce', 'contabilidad@unidekor.com.mx': 'Retailer', 'designer@greda.com': 'Retailer', 'perssons@perssonsgulvteknik.dk': 'Retailer', 'lais@coveringsetc.com': 'Manufacturer', 'kortiz@haustileco.com': 'Manufacturer', 'angelo@garagesolver.com': 'Retailer', 'info@epoxypower.com': 'Retailer', 'kory@epoxygenius.com': 'Retailer', 'chad.paulson@twincityepoxydocs.com': 'Retailer', 'peter@epoxyprosofnewengland.com': 'Retailer', 'erica@integritygaragefloors.com': 'Retailer', 'info@bullepoxycoating.ca': 'Retailer', 'erinm@iawlight.com': 'Retailer', 'epoxytime@gmail.com': 'Retailer', 'https://dashboard.stripe.com/customers/cus_oieh1n0cqqejtr': 'Retailer', 'office@austriaauction.com': 'Retailer', 'chelsea@geontile.com': 'Manufacturer', 'management@kobin.co.id': 'Retailer', 'gurmeet.singh@thakral.com': 'Ecommerce', 'nicolas-uribe@rugs2go.com': 'Ecommerce', 'jennifer.berry@staufusa.com': 'Manufacturer', 'jimh@croccoatings.com': 'Retailer', 'corey@pnwwash.com': 'Retailer', 'hello@habitflooring.co.uk': 'Manufacturer', 'magdalenakinska@woodconnexions.com': 'Retailer', 'suzana@bdesign.com.br': 'Retailer', 'adriana@scgruposc.com.br': 'Retailer', 'jecilenemartinscosta@gmail.com': 'Retailer', 'pisolambc@hotmail.com': 'Retailer', 'lucas.andrade@luzzo.com.br': 'Manufacturer', 'bernardovascon13@gmail.com': 'Retailer', 'aaron@newfloorsusa.com': 'Retailer', 'josh.billings@woodpeckerflooring.com': 'Manufacturer', 'kahmad@cassinelli.com': 'Ecommerce', 'david@floorily.com': 'Manufacturer', 'cgaines@etwcreations.com': 'Retailer', 'nleonhardt@pisosalemanes.com': 'Retailer', 'chris@allpurposecoatings.com.au': 'Retailer', 'lalvarado@dicsamexico.com.mx': 'Manufacturer', 'sclem@lonestarsupplyabi.com': 'Retailer', 'info@efcqld.com': 'Retailer', 'rogerio@noiiz.com.br': 'Retailer', 'clinton@gedsfloorstore.com': 'Retailer', 'soslaertelaminados@hotmail.com': 'Retailer', 'geral@blossomhomedecor.pt': 'Ecommerce', 'marcelo@frankmilicarpetes.com.br': 'Retailer', 'baris@kristalcarpets.co.za': 'Ecommerce', 'pooran@easystepflooring.co.uk': 'Ecommerce', 'ali@finalspecs.com': 'Retailer', 'info@floorsandwalls.ae': 'Distributor', 'juh_cardosoo@hotmail.com': 'Retailer', 'salih@abrashcarpets.com': 'Ecommerce', 'oaldail@alghomlas.co': 'Retailer', 'info@duphill.com': 'Manufacturer', 'abdullah@sgc.com.kw': 'Retailer', 'don@granicreteaustralia.com.au': 'Retailer', 'office@814epoxyandmore.com': 'Retailer', 'daynanjohnson@yahoo.com': 'Retailer', 'greg@allaroundsurfaces.com': 'Retailer', 'jeremy@guardiangarage.com': 'Retailer', 'marc@garagefloors4less.com': 'Retailer', 'alexloesing@monstercote.com': 'Retailer', 'carlos.herrera@garageexperts.com': 'Retailer', 'brianna@creativecoatingslv.com': 'Retailer', 'bellaandrews1031@gmail.com': 'Retailer', 'pamela.novak@jetrockinc.com': 'Manufacturer', 'chelseas@motorcityfloorsandcoatings.com': 'Retailer', 'ben@zonegarageokc.com': 'Retailer', 'usaconcretecoatings@gmail.com': 'Retailer', 'trevin@twistedfloors.com': 'Retailer', 'alex@tsrconcretecoatings.com': 'Retailer', 'invoices@trugritgarageflooring.com': 'Retailer', 'shawn@surfacemastersflorida.com': 'Retailer', 'wecare@coattherockies.com': 'Retailer', 'lori.rossi@centimark.com': 'Retailer', 'nathan@premier-edge.com': 'Retailer', 'dov@carmelgroup.co.il': 'Ecommerce', 'contact@triff.com': 'Ecommerce', 'info@koremanmaastricht.nl': 'Retailer', 'info@kelim.nl': 'Ecommerce', 'info@chrissycrater.com': 'Ecommerce', 'adil@primepersian.co.za': 'Manufacturer', 'afshin@unitexint.com': 'Ecommerce', 'julia.schlosser@schmidt-ausstatter.de': 'Ecommerce', 'info@acsento.com': 'Retailer', 'contato@tapecartes.com': 'Ecommerce', 'waltertwrocha@gmail.com': 'Retailer', 'chris.f@functionalfloors.com': 'Retailer', 'ramon@bagehome.com.au': 'Ecommerce', 'sanaa@benisouk.com': 'Ecommerce', 'shezadhassan22@gmail.com': 'Retailer', 'hello+tapijtcentrumnl@floori.io': 'Ecommerce', 'hello@rugtales.com': 'Ecommerce', 'info@sydepoxyflooring.com.au': 'Retailer', 'jacob@qepoxy.com.au': 'Manufacturer', 'steve@envirocoat.com.au': 'Manufacturer', 'dion@epoxy2uaustralia.com': 'Retailer', 'info@durableconcretecoatings.com.au': 'Ecommerce', 'ensari5avc@gmail.com': 'Ecommerce', 'mannyaar@gmail.com': 'Manufacturer', 'accounts@allgrind.com.au': 'Manufacturer', 'andrew@abbeytimber.com.au': 'Manufacturer', 'olivier@unamourdetapis.com': 'Retailer', 'ap@a1garage.com': 'Retailer', 'jmikatich@lwmountain.com': 'Distributor', 'crayton@level10coatings.com': 'Retailer', 'fernanda@indusparquetsp.com.br': 'Manufacturer', 'ashley.scott@divinefloor.com': 'Manufacturer', 'adwbigmad@gmail.com': 'Ecommerce', 'customercare@obeetee.com': 'Manufacturer', 'info@bazaarvelvet.co.uk': 'Retailer', 'machaleflooring@gmail.com': 'Retailer', 'khaled@zahitrade.com': 'Manufacturer', 'shelley@eva-last.com': 'Manufacturer', 'marketing@flooring365.co.uk': 'Ecommerce', 'eva@evalution.co.za': 'Retailer', 'vicky.h@solet.me': 'Retailer', 'ejsaccon@cejatel.com.br': 'Manufacturer', 'edanielli@alberdi.com.ar': 'Manufacturer', 'kelly@aerofloorcoatings.com': 'Retailer', 'mkt@portilato.com.br': 'Retailer', 'onlineaccounts@rugsoriginal.co.za': 'Ecommerce', 'marketing@avanti-koberce.cz': 'Distributor', 'dennis@onedayfloors.com': 'Retailer', 'zanella_vidracaria@hotmail.com': 'Retailer', 'diretoria@stilorustico.com.br': 'Retailer', 'reginaldo@ofpisos.com.br': 'Retailer', 'renatoadeon@hotmail.com': 'Retailer', 'financeiro@juniordecoracoes.com.br': 'Retailer', 'dzukinteriores@gmail.com': 'Retailer', 'construbelmateriais@gmail.com': 'Retailer', 'pedro@casinhabela.com.br': 'Ecommerce', 'financeiro@c-artambientacoes.com.br': 'Retailer', 'alexsandrolohn@uol.com.br': 'Retailer', 'fernanda.delamonica@terra.com.br': 'Retailer', 'marketing@artecdesign.com.br': 'Retailer', 'denis.staudt@herval.com.br': 'Retailer', 'contato@refinattoacabamentos.com.br': 'Retailer', 'comercial@revestart.com.br': 'Retailer', 'terezinhabarbosapadilha@gmail.com': 'Retailer', 'rodrigo.garcia@bellar.com.br': 'Retailer', 'sales@hardwoods4less.com': 'Ecommerce', 'krzysztof.majewski@epufloor.com': 'Manufacturer', 'bashir.a@nextone.com.au': 'Retailer', 'ryankeats87@gmail.com': 'Manufacturer', 'filip@tapijtendemuynck.be': 'Retailer', 'leoansanellorocha@gmail.com': 'Retailer', 'carpecril@hotmail.com': 'Retailer', 'matheussolidfloorsp@gmail.com': 'Retailer', 'cesar.braz@panoramahomecenter.com.br': 'Retailer', 'dipisocuritiba@dipisocuritiba.com.br': 'Distributor', 'rafamanchine1@gmail.com': 'Retailer', 'adriano.navarini@lojareformular.com.br': 'Ecommerce', 'jmdivisorias@jmdecoracoes.com.br': 'Retailer', 'erik@copafer.com.br': 'Ecommerce', 'alisson.santos@ciasul.com.br': 'Retailer', 'hannacorumba@gmail.com': 'Retailer', 'web@sparksfitness.net': 'Retailer', 'administrativo@decorandobem.com.br': 'Retailer', 'jon@dctuk.com': 'Ecommerce', 'fan@premiumflooringdirect.com': 'Distributor', 'luxurylandksa@gmail.com': 'Retailer', 'israel.dias@quero-quero.com.br': 'Retailer', 'chris@webfootpainting.com': 'Retailer', 'sales@smartertimberflooring.com.au': 'Manufacturer', 'sac@hometeck.com.br': 'Retailer', 'payam@maltarugs.com': 'Ecommerce', 'marketing@passalacqua.com.br': 'Retailer', 'office@allsealed.com': 'Retailer', 'yunus.karadeniz@floksertekstil.com.tr': 'Manufacturer', 'rmullen@flooringsolutions.us': 'Manufacturer', 'info@colortekstr.com': 'Retailer', 'divisulsc@gmail.com': 'Retailer', 'emil@worldoffloors.com': 'Retailer', 'rafaelterna@evolucaopisos.com.br': 'Retailer', 'fernanda@mademolliz.com.br': 'Retailer', 'gustavo.cardoso@villagres.com.br': 'Manufacturer', 'samuel@arqpisos.com.br': 'Distributor', 'justas@staki.lt': 'Retailer', 'admin@pisosalemanes.com': 'Retailer', 'agp@casarara.com.br': 'Retailer', 'rocco@rugalia.com': 'Ecommerce', 'willfazz@hotmail.com': 'Retailer', 'sheila.barros@fastdecorpisos.com.br': 'Retailer', 'pisobelo@pisobelo.com.br': 'Retailer', 'vendas@villaattuale.com.br': 'Retailer', 'dev@originate.ie': 'Retailer', 'marco@bestwoolcarpets.com': 'Manufacturer', 'webdeveloper@surfaces-me.com': 'Manufacturer', 'fabiolachagas@arabescodecor.com.br': 'Retailer', 'ilka.pratesaguiar@gmail.com': 'Retailer', 'veronica@ozgrind.com.au': 'Retailer', 'jack@solomons.com.au': 'Manufacturer', 'info@your1dayfloor.com': 'Retailer', 'mercadeo@listo.co': 'Retailer', 'cepisa2000@hotmail.com': 'Ecommerce', 'domovie@andersens.com.au': 'Ecommerce', 'avelarde@dib.cl': 'Ecommerce', 'marketing1@madel.com.br': 'Manufacturer', 'info@rugsgalore.com.au': 'Ecommerce', 'wsilva@ceramicaportoferreira.com.br': 'Manufacturer', 'info@ultimatefloors.com.au': 'Manufacturer', 'info@dolcevitahali.com': 'Manufacturer', 'info@toughfloors.com.au': 'Manufacturer', 'jessica@rugsforgood.com.au': 'Ecommerce', 'nicolaujet@gmail.com': 'Retailer', 'edyta.widlak@e-floor.pl': 'Ecommerce', 'faeghip@yahoo.com': 'Ecommerce', 'hello+komfort@floori.io': 'Ecommerce', 'sina@iconicrugs.com.au': 'Ecommerce', 'marilia@koord.com.br': 'Ecommerce', 'nick@nationalconcretecoatings.com': 'Manufacturer', 'ornaredd@gmail.com': 'Manufacturer', 'fabio.upfloor@gmail.com': 'Retailer', 'luizflavio@emporioconstruir.com.br': 'Retailer', 'livesti.contato@gmail.com': 'Retailer', 'halicizadekurumsal@gmail.com': 'Retailer', 'vitor@lumeceramica.com.br': 'Manufacturer', 'artisan_rugs@iinet.net.au': 'Manufacturer', 'anilbaltaci@sultanhali.com.tr': 'Manufacturer', 'talorsroom@gmail.com': 'Ecommerce', 'info@vanheugtentapijttegels.nl': 'Ecommerce', 'ehalicim016@gmail.com': 'Ecommerce', 'administrativo@casarug.com.br': 'Retailer', 'accounts@everfloor.com.au': 'Ecommerce', 'robertob@tecertapetes.com.br': 'Retailer', 'guilherme@tapetessaocarlos.com.br': 'Manufacturer', 'office@wearmax.at': 'Manufacturer', 'nasser@nassernishaburi.com': 'Retailer', 'matan@villagiowoodfloors.com': 'Manufacturer', 'manager@alfombrashamid.es': 'Ecommerce', 'contato@zinihome.com.br': 'Distributor', 'sarah@sydneyrugsonline.com.au': 'Ecommerce', 'sales@nextdayflooringuk.co.uk': 'Retailer', 'jcborjas@cpersa.com': 'Ecommerce', 'justin@precisionflooringhawaii.com': 'Retailer', 'michelleknaesel@gmail.com': 'Retailer', 'janl@slccflooring.com': 'Distributor', 'comercial@agrolatina.com.br': 'Ecommerce', 'k.rifaat@leorugs.com': 'Manufacturer', 'marlena.korona@coniveo.pl': 'Distributor', 'marciadecora01@gmail.com': 'Retailer', 'adam@floormasters.co.nz': 'Retailer', 'jake@lumberjackdirect.com': 'Retailer', 'r.martin@niazi.com.br': 'Ecommerce', 'dalton@cyrusrugs.com.au': 'Ecommerce', 'chavmarcelo@gmail.com': 'Retailer', 'rhaabibe@rhinaradecoracoes.com.br': 'Retailer', 'sibylle@maison-s.com': 'Retailer', 'info@rugsoflondon.com': 'Ecommerce', 'zilmar@hazz.com.br': 'Ecommerce', 'cohutchings@gmail.com': 'Retailer', 'celso@zariftapetes.com.br': 'Retailer', 'contato@tapecariamarcelo.com.br': 'Retailer', 'jonathan@kapazi.com.br': 'Manufacturer', 'bergstromn@valenciahardwoods.com': 'Manufacturer', 'gomes@rarorequinte.com.br': 'Manufacturer', 'hello+mazurskadeska@floori.io': 'Retailer', 'contato@sagadecoracao.com.br': 'Retailer', 'socialmedia@nabina.com': 'Retailer', 'cate.vanegas@bona.com': 'Manufacturer', 'amanda.arsenault@pravadafloors.com': 'Manufacturer', 'melhem@hariz.com.br': 'Retailer', 'nfo@polishfloors.pl': 'Manufacturer', 'henrique@kyowatapetes.com.br': 'Retailer', 'k.rifaat+sg@leorugs.com': 'Retailer', 'davidw@carpetcall.com.au': 'Retailer', 'magalli.fernandez@ribadao.com': 'Manufacturer', 'burak@the-rugs.com': 'Ecommerce', 'sopiso@sopiso.com.br': 'Ecommerce', 'rm@tapetart.com.br': 'Retailer', 'dean@onlineflooringstore.com.au': 'Ecommerce', 'info@ohhappyhome.com.au': 'Manufacturer', 'daniele.colcelli@stile.com': 'Manufacturer', 'biuro@profidomo.pl': 'Retailer', 'info@cheaprugsaustralia.com.au': 'Ecommerce', 'hello@ruglove.co.uk': 'Retailer', 'starrugs@outlook.com': 'Ecommerce', 'hello+grupafachowiec@floori.io': 'Retailer', 'benjamin@kustomtimber.com.au': 'Manufacturer', 'hello+kronospan@floori.io': 'Manufacturer', 'tony.han@carpetcourt.com.au': 'Retailer', 'gabriel.gomes@belgotex.com.br': 'Manufacturer', 'shop@jaipurrugs.com': 'Manufacturer', 'salesfloorsadelaide@gmail.com': 'Manufacturer', 'daniel.felix@rcpisos.com.br': 'Retailer', 'info@rugweave.in': 'Retailer', 'ryan@unitedfloorcoatings.com': 'Retailer', 'eduardo.pacheco@tekno-step.com': 'Manufacturer', 'marketing@hausz.com.br': 'Retailer', 'randy.jordan@thefloorstorenm.com': 'Retailer', 'james@tendadostapetes.com.br': 'Ecommerce', 'roni@viastar.com.br': 'Distributor', 'parkiethajnowka@parkiethajnowka.pl': 'Retailer', 'yagmur.imdad@gumussuyu.com.tr': 'Manufacturer', 'magdalenakinska@zenonfloors.com': 'Retailer', 'tienda@alfombrasnelo.com': 'Retailer', 'pdib@bazhars.cl': 'Ecommerce', 'christine@coastalhamptons.com.au': 'Ecommerce', 'info@zigler.es': 'Retailer', 'contato@tapetah.com.br': 'Distributor', 'pawel.gawior@barlinek.com.pl': 'Manufacturer', 'cpd@doural.com.br': 'Retailer', 'biuro@finishparkiet.com.pl': 'Manufacturer', 'office@wolverineflooring.com': 'Retailer', 'yulong@uacarpet.com.sg': 'Manufacturer', 'scott@leggari.com': 'Manufacturer', 'yusufsahinn02@gmail.com': 'Retailer', 'info@dicarpet.com': 'Manufacturer', 'marketing@multiform.pl': 'Distributor', 'john@cronz.co.nz': 'Ecommerce', 'marcin.owsiany@swisskrono.com': 'Manufacturer', 'adrian@parkietstudio.pl': 'Ecommerce', 'info@bijan.com.au': 'Retailer', 's.sklepik@jawor-parkiet.pl': 'Manufacturer'}

def _resolve_customer_type(cust_id: str, email: str, meta_type: str) -> str:
    """Resolve customer type: HubSpot ID match > HubSpot email match > Stripe metadata."""
    if cust_id:
        t = _HS_TYPE_BY_ID.get(cust_id)
        if t:
            return t
    if email:
        t = _HS_TYPE_BY_EMAIL.get(email.lower())
        if t:
            return t
    return meta_type or ""


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
            # Try address object first, then dict fallback, then shipping
            country = ""
            cust_type = ""
            try:
                addr = getattr(cust, "address", None)
                if addr:
                    country = _normalize_country((getattr(addr, "country", None) or ""))
                cust_d = cust.to_dict() if hasattr(cust, "to_dict") else {}
                if not country:
                    country = _normalize_country(
                        (cust_d.get("address") or {}).get("country") or
                        (cust_d.get("shipping") or {}).get("address", {}).get("country") or ""
                    )
                meta = cust_d.get("metadata") or {}
                meta_type = (meta.get("type") or meta.get("customer_type") or
                             meta.get("segment") or meta.get("industry") or
                             meta.get("category") or "").strip()
                cust_type = _resolve_customer_type(cust_id, email, meta_type)
            except Exception:
                country = country or ""

        display = name or email or cust_id
        label   = stripe_status_to_label(sub.status)

        try:
            sub_dict = sub.to_dict()
        except Exception:
            sub_dict = {}

        items_data = sub_dict.get("items", {}).get("data", [])
        item = items_data[0] if items_data else {}
        price    = item.get("price", {}) or {}
        currency = (price.get("currency") or "usd").lower()
        rec      = (price.get("recurring") or {})
        interval = "Annual" if rec.get("interval") == "year" else "Monthly"
        # Sum ALL items × quantity (handles multi-item subscriptions correctly)
        total_cents = sum(
            ((it.get("price") or {}).get("unit_amount") or 0) * ((it.get("quantity") or 1))
            for it in (items_data or [item])
        )
        amount_usd = round(_to_usd(total_cents, currency), 2)

        # Currency-based country fallback (applied after currency is defined)
        if not country:
            country = _CURRENCY_COUNTRY.get(currency, "")

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
                "active_usd": amount_usd if label == "Active" else 0.0,
                "proj":       proj,
                "next_inv":   next_inv,
                "country":    country,
                "cust_type":  cust_type,
            }
        else:
            ex = customers[cust_id]
            if not ex.get("cust_type") and cust_type:
                ex["cust_type"] = cust_type
            # Escalate status if worse
            if priority.get(label, 0) > priority.get(ex["status"], 0):
                ex["status"]   = label
                ex["next_inv"] = next_inv
            # Sum projections and amounts (customer may have multiple subs)
            ex["proj"]       = [round(a + b, 2) for a, b in zip(ex["proj"], proj)]
            ex["amount_usd"] = round(ex["amount_usd"] + amount_usd, 2)
            if label == "Active":
                ex["active_usd"] = round(ex.get("active_usd", 0.0) + amount_usd, 2)

    rows = []
    for info in customers.values():
        rows.append([
            info["name"],               # 0
            info["status"],             # 1
            info["interval"],           # 2
            info["amount_usd"],         # 3 total (all subs)
            info["proj"],               # 4
            info["next_inv"],           # 5
            info.get("country",""),     # 6
            info.get("cust_type",""),   # 7
            info.get("active_usd",0.0), # 8 active-only amount (for MRR accuracy)
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
    """
    MRR/ARR from active subscriptions — matches Stripe's own MRR calculation:
    - Includes ALL currencies (converted to USD via FX rates)
    - Sums ALL items in each subscription
    - Multiplies by quantity
    - Annual subscriptions divided by 12 for MRR equivalent
    """
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
            for item in items:
                price    = item.get("price", {}) or {}
                amount   = price.get("unit_amount", 0) or 0
                currency = (price.get("currency", "usd") or "usd").lower()
                interval = (price.get("recurring", {}) or {}).get("interval", "month")
                quantity = item.get("quantity", 1) or 1
                if not amount:
                    continue
                # Convert to USD — includes BRL, AUD, EUR, GBP, etc.
                # _to_usd already returns dollars (divides cents by 100 internally)
                amount_usd = _to_usd(amount * quantity, currency)
                if not amount_usd:
                    continue
                if interval == "year":
                    annual_arr   += amount_usd
                    annual_count += 1
                else:
                    monthly_mrr   += amount_usd
                    monthly_count += 1
        except Exception:
            continue

    # Count active subscriptions (matches Stripe's "Assinantes ativos")
    active_subs = sum(
        1 for sub in subs
        if stripe_status_to_label(sub.status) == "Active"
    )
    # MRR breakdown by customer type — computed here so interval+amount are handled
    # correctly per-subscription (avoids mixed-interval bug in JS row aggregation)
    mrr_by_type: dict = {}
    for sub in subs:
        if stripe_status_to_label(sub.status) != "Active":
            continue
        try:
            sd = sub.to_dict()
            # customer may be an ID string or an expanded dict
            cust_raw = sd.get("customer") or ""
            if isinstance(cust_raw, dict):
                cid = cust_raw.get("id", "")
            elif hasattr(cust_raw, "id"):
                cid = cust_raw.id
            else:
                cid = str(cust_raw)
            ctype = _HS_TYPE_BY_ID.get(cid, "") or "Unclassified"
            for it in (sd.get("items", {}).get("data", []) or []):
                p   = it.get("price", {}) or {}
                amt = (p.get("unit_amount") or 0) * ((it.get("quantity") or 1))
                cur = (p.get("currency") or "usd").lower()
                itv = (p.get("recurring") or {}).get("interval", "month")
                usd = _to_usd(amt, cur)
                if not usd:
                    continue
                mrr_contrib = usd / 12 if itv == "year" else usd
                mrr_by_type[ctype] = round(mrr_by_type.get(ctype, 0.0) + mrr_contrib, 2)
        except Exception:
            continue
    return {
        "monthly_mrr":   round(monthly_mrr, 2),
        "annual_arr":    round(annual_arr, 2),
        "annual_mrr":    round(annual_arr / 12, 2),
        "total_mrr":     round(monthly_mrr + annual_arr / 12, 2),
        "monthly_count": monthly_count,
        "annual_count":  annual_count,
        "active_subs":   active_subs,
        "mrr_by_type":   mrr_by_type,
    }


def fetch_today_invoices(subs):
    """
    Fetch all successful charges since yesterday midnight UTC.
    Using 'since yesterday midnight' instead of 'last 24h rolling window' ensures
    all transactions from the previous calendar day are always shown, regardless
    of what time the script runs.
    Uses charge.succeeded events (covers subscriptions AND one-time charges).
    """
    # Yesterday midnight UTC — always show the full previous day
    now       = datetime.now(timezone.utc)
    yesterday = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    # If it's before noon UTC, also include the day before yesterday
    # so transactions from 2 days ago aren't missed on early-morning runs
    if now.hour < 12:
        import calendar as _cal
        d = yesterday - __import__('datetime').timedelta(days=1)
        yesterday = d
    since = int(yesterday.timestamp())

    seen = set()
    results = []
    try:
        params = {"type": "charge.succeeded", "created": {"gte": since}, "limit": 100}
        while True:
            page = stripe.Event.list(**params)
            for event in page.data:
                try:
                    ev_dict   = event.to_dict()
                    charge    = ev_dict.get("data", {}).get("object", {}) or {}
                    charge_id = charge.get("id", "")
                    if charge_id in seen:
                        continue
                    # Only captured, non-refunded charges
                    if not charge.get("captured", False):
                        continue
                    if charge.get("refunded", False):
                        continue
                    amount   = _to_usd(charge.get("amount", 0), charge.get("currency", "usd"))
                    if amount <= 0:
                        continue
                    ts       = ev_dict.get("created", 0)
                    dt_str   = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%b %d %H:%M UTC") if ts else ""
                    # Use email as identifier (more meaningful than cardholder name or invoice ID)
                    billing  = charge.get("billing_details") or {}
                    cname    = (billing.get("name") or
                                billing.get("email") or
                                charge.get("receipt_email") or
                                charge.get("customer") or
                                "Unknown")
                    seen.add(charge_id)
                    results.append({"name": cname, "amount": amount, "time": dt_str})
                except Exception:
                    continue
            if not page.has_more:
                break
            params["starting_after"] = page.data[-1].id
    except Exception as e:
        print(f"  Warning (charges): {e}")
    results.sort(key=lambda x: x["time"], reverse=True)
    print(f"  {len(results)} charge(s) since {yesterday.strftime('%Y-%m-%d')} UTC")
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
    # Unknown rate: log and return 0 (better than silently treating as USD)
    if cur not in ("", "USD"):
        print(f"  Warning: no FX rate for {cur}, skipping amount {amount:.2f}")
    return 0.0


def _fetch_month_collected(mi):
    """
    Fetch total USD collected for a single month index (0=Jan..11=Dec).
    Filters by status_transitions.paid_at (when actually paid), NOT by invoice created date.
    Fetches a 60-day window before the month start to catch invoices created earlier but paid this month.
    """
    from datetime import timedelta
    month_start = datetime(2026, mi + 1, 1, tzinfo=timezone.utc)
    month_end   = datetime(2027, 1, 1, tzinfo=timezone.utc) if mi == 11 else datetime(2026, mi + 2, 1, tzinfo=timezone.utc)
    # Go back 60 days to catch invoices created before the month but paid during it
    fetch_from  = month_start - timedelta(days=60)
    total = 0.0
    try:
        params = {
            "status":  "paid",
            "created": {"gte": int(fetch_from.timestamp()), "lte": int(month_end.timestamp())},
            "limit":   100,
        }
        while True:
            page = stripe.Invoice.list(**params)
            for inv in page.data:
                try:
                    d = inv.to_dict()
                    # Only count invoices with an actual payment (amount_paid > 0).
                    # This excludes invoices fully covered by credit balance (amount_paid=0)
                    # while including both charge_automatically and send_invoice paid by card.
                    # Note: ~$7k/year excess from manually-marked invoices is acceptable
                    # without Balance Transactions: Read permission.
                    if not d.get("amount_paid"):
                        continue
                    paid_at = (d.get("status_transitions") or {}).get("paid_at") or 0
                    if not paid_at:
                        continue
                    paid_dt = datetime.fromtimestamp(int(paid_at), tz=timezone.utc)
                    if _month_index(paid_dt) != mi:
                        continue
                    amount = _to_usd(d.get("amount_paid", 0), d.get("currency", "usd"))
                    if amount > 0:
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
    CACHE_VER = "v3"  # v3: payment_intent filter replaces collection_method
    try:
        with open(cache_file) as f:
            raw = json.load(f)
        # If version doesn't match, discard old cache so values recalculate
        cache = raw if raw.get("__version__") == CACHE_VER else {}
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
            cache["__version__"] = "v2"
            with open(cache_file, "w") as f:
                json.dump(cache, f, indent=2)
            print(f"  collected_cache.json updated ({sum(1 for v in cache.values() if v>0)} months)")
        except Exception as e:
            print(f"  Warning: could not save cache: {e}")

    return collected

def _fetch_month_volume(mi):
    """
    Fetch Gross Volume (succeeded PaymentIntents) and Refund Volume for one month.
    Returns dict with gross, refunds, net, gross_count, refund_count.
    """
    month_start = datetime(2026, mi + 1, 1, tzinfo=timezone.utc)
    month_end   = datetime(2027, 1, 1, tzinfo=timezone.utc) if mi == 11 else datetime(2026, mi + 2, 1, tzinfo=timezone.utc)
    start_ts, end_ts = int(month_start.timestamp()), int(month_end.timestamp())

    gross, gross_count = 0.0, 0
    try:
        params = {"created": {"gte": start_ts, "lte": end_ts}, "limit": 100}
        while True:
            page = stripe.PaymentIntent.list(**params)
            for pi in page.data:
                try:
                    d = pi.to_dict()
                    if d.get("status") != "succeeded":
                        continue
                    amt = d.get("amount_received", 0) or 0
                    if amt <= 0:
                        continue
                    cur = (d.get("currency") or "usd").lower()
                    usd = _to_usd(amt, cur)
                    if usd > 0:
                        gross = round(gross + usd, 2)
                        gross_count += 1
                except Exception:
                    continue
            if not page.has_more:
                break
            params["starting_after"] = page.data[-1].id
    except Exception as e:
        print(f"  Warning fetching volume month {mi+1}: {e}")

    refunds, refund_count = 0.0, 0
    try:
        params = {"created": {"gte": start_ts, "lte": end_ts}, "limit": 100}
        while True:
            page = stripe.Refund.list(**params)
            for ref in page.data:
                try:
                    d = ref.to_dict()
                    if d.get("status") != "succeeded":
                        continue
                    amt = d.get("amount", 0) or 0
                    if amt <= 0:
                        continue
                    cur = (d.get("currency") or "usd").lower()
                    usd = _to_usd(amt, cur)
                    if usd > 0:
                        refunds = round(refunds + usd, 2)
                        refund_count += 1
                except Exception:
                    continue
            if not page.has_more:
                break
            params["starting_after"] = page.data[-1].id
    except Exception as e:
        print(f"  Warning fetching refunds month {mi+1}: {e}")

    return {
        "gross": gross, "refunds": refunds, "net": round(gross - refunds, 2),
        "gross_count": gross_count, "refund_count": refund_count,
    }


def fetch_monthly_volume():
    """
    Fetch Gross/Refund/Net Volume per month for Jan-Dec 2026.
    Cached in volume_cache.json — past months frozen, current always re-fetched.
    """
    cache_file = "volume_cache.json"
    CACHE_VER  = "v1"
    try:
        with open(cache_file) as f:
            raw = json.load(f)
        cache = raw if raw.get("__version__") == CACHE_VER else {}
    except Exception:
        cache = {}

    now = datetime.now(timezone.utc)
    current_mi = (now.month - 1) if now.year == 2026 else (12 if now.year > 2026 else 0)

    gross_arr = [0.0]*12; refund_arr = [0.0]*12; net_arr = [0.0]*12
    cache_updated = False

    for mi in range(12):
        key = f"2026-{mi+1:02d}"
        if mi < current_mi and key in cache:
            v = cache[key]
            gross_arr[mi]  = v.get("gross",   0.0)
            refund_arr[mi] = v.get("refunds", 0.0)
            net_arr[mi]    = v.get("net",     0.0)
        else:
            v = _fetch_month_volume(mi)
            gross_arr[mi]  = v["gross"]
            refund_arr[mi] = v["refunds"]
            net_arr[mi]    = v["net"]
            if mi < current_mi:
                cache[key] = v
                cache_updated = True
                print(f"  Volume {key}: gross=${v['gross']:,.0f} refunds=${v['refunds']:,.0f} net=${v['net']:,.0f}")

    if cache_updated:
        try:
            cache["__version__"] = CACHE_VER
            with open(cache_file, "w") as f:
                json.dump(cache, f, indent=2)
            print(f"  volume_cache.json saved")
        except Exception as e:
            print(f"  Warning: could not save volume cache: {e}")

    return gross_arr, refund_arr, net_arr



def render_html(rows, totals, active_tot, problem_tot, synced, metrics, today_invoices, monthly_collected, monthly_gross=None, monthly_refunds=None, monthly_net=None):
    rows_js          = json.dumps(rows, ensure_ascii=False)
    totals_js        = json.dumps(totals)
    collected_js     = json.dumps(monthly_collected)
    mrr_by_type_js   = json.dumps(metrics.get("mrr_by_type", {}), separators=(",",":"))
    problem_tot_js   = json.dumps([round(x,2) for x in problem_tot], separators=(",",":"))
    gross_js         = json.dumps([round(x,2) for x in (monthly_gross   or [0]*12)], separators=(",",":"))
    refunds_js       = json.dumps([round(x,2) for x in (monthly_refunds or [0]*12)], separators=(",",":"))
    net_js           = json.dumps([round(x,2) for x in (monthly_net     or [0]*12)], separators=(",",":"))
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
.card-title{{font-size:12px;font-weight:600;color:var(--text);text-transform:uppercase;letter-spacing:.04em;margin-bottom:14px}}
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
.cmp-mo{{font-size:15px;font-weight:500;color:var(--text)}}
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
thead th:hover{{background:var(--bg3);color:var(--text)}}
thead th .sort-ind{{font-size:10px;margin-left:2px;opacity:.8}}
.month-strip{{display:flex;align-items:center;gap:8px;background:var(--bg);border:0.5px solid var(--border2);border-radius:var(--rl);padding:6px 8px;margin-bottom:1.5rem}}
.ms-arrow{{background:none;border:0.5px solid var(--border);border-radius:var(--r);width:32px;height:32px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--text2);font-size:16px;flex-shrink:0;transition:all .15s}}
.ms-arrow:hover{{background:var(--bg2);color:var(--text)}}
.ms-pills{{display:flex;flex:1;gap:2px}}
.ms-pill{{flex:1;padding:8px 4px;border:none;border-radius:var(--r);cursor:pointer;font-size:13px;font-weight:500;color:var(--text3);background:transparent;transition:all .15s;white-space:nowrap}}
.ms-pill:hover{{background:var(--bg2);color:var(--text)}}
.ms-pill.active{{background:var(--green);color:#fff;font-weight:700}}
.ms-yr.active{{background:var(--blue);color:#fff}}
.ms-yr{{border-left:0.5px solid var(--border2);margin-left:4px;padding-left:8px}}

/* Info tooltip */
.info-btn{{position:relative;display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;border-radius:50%;background:var(--bg2);border:0.5px solid var(--border);color:var(--text3);font-size:9px;font-weight:700;cursor:pointer;flex-shrink:0;vertical-align:middle;margin-left:5px;line-height:1;transition:all .15s;user-select:none}}
.info-btn:hover,.info-btn.open{{background:var(--bg3);color:var(--text2);border-color:var(--text3)}}
.info-tip{{display:none;position:absolute;z-index:99;bottom:calc(100% + 7px);left:50%;transform:translateX(-50%);width:220px;background:var(--bg);border:0.5px solid var(--border2);border-radius:var(--r);padding:9px 11px;font-size:12px;color:var(--text2);line-height:1.5;box-shadow:0 4px 16px rgba(0,0,0,.2);pointer-events:none}}
.info-tip::after{{content:"";position:absolute;top:100%;left:50%;transform:translateX(-50%);border:5px solid transparent;border-top-color:var(--border2)}}
.info-btn.open .info-tip{{display:block}}
.info-btn:hover .info-tip{{display:block}}
@media(max-width:700px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.row2,.analytics-grid{{grid-template-columns:1fr}}.ms-pill{{font-size:11px;padding:6px 2px}}}}
/* tabs */
.tabs{{display:flex;gap:2px;margin-bottom:1.5rem;background:var(--bg2);border-radius:var(--rl);padding:4px}}
.tab-btn{{flex:1;padding:8px 16px;border:none;border-radius:var(--r);cursor:pointer;font-size:13px;font-weight:500;color:var(--text2);background:transparent;transition:all .15s}}
.icon-btn{{display:inline-flex;align-items:center;gap:5px;border:0.5px solid var(--border);border-radius:var(--r);padding:6px 12px;font-size:12px;font-weight:500;cursor:pointer;background:var(--bg);color:var(--text2);transition:all .15s;text-decoration:none}}
.icon-btn:hover{{background:var(--bg2);color:var(--text)}}
.icon-btn svg{{width:14px;height:14px;flex-shrink:0}}
.tab-btn.active{{background:var(--bg);color:var(--text);box-shadow:0 1px 3px rgba(0,0,0,.08)}}
/* analytics */
.analytics-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:1.5rem}}
.ctry-row{{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:0.5px solid var(--border2)}}
.ctry-row:last-child{{border-bottom:none}}
.ctry-name{{font-size:13px;font-weight:500;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:120px}}
.ctry-bar-wrap{{width:90px;height:6px;background:var(--bg2);border-radius:3px;overflow:hidden;flex-shrink:0}}
.ctry-bar-fill{{height:100%;border-radius:3px;background:var(--gbar)}}
.ctry-val{{font-size:12px;font-variant-numeric:tabular-nums;width:56px;text-align:right;flex-shrink:0}}
.ctry-count{{font-size:11px;color:var(--text3);width:36px;text-align:right;flex-shrink:0}}
.type-pill{{display:inline-flex;align-items:center;gap:4px;font-size:12px;padding:3px 10px;border-radius:20px;background:var(--bg2);color:var(--text2);margin:3px}}
.type-unknown{{font-size:12px;color:var(--text3);font-style:italic;padding:8px 0}}
</style>
</head>
<body>
<div class="wrap">

  <div class="topbar">
    <div>
      <h1><span class="si">◈</span> Floori.io — Revenue Dashboard</h1>
      <p class="synced">Last synced: {synced} · Auto-updated weekdays at 9:30 AM BRT</p>
    </div>
    <div style="display:flex;gap:8px;align-items:center">
      <div class="tabs" style="margin-bottom:0">
        <button class="tab-btn active" id="tab-overview" onclick="switchTab('overview')">Overview</button>
        <button class="tab-btn" id="tab-analytics" onclick="switchTab('analytics')">Analytics</button>
      </div>
      <button class="icon-btn" onclick="location.reload()">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M13.5 8A5.5 5.5 0 1 1 8 2.5c1.8 0 3.4.87 4.4 2.2"/><path d="M13.5 2.5v2.2H11.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
        Refresh
      </button>
      <button class="icon-btn" onclick="exportCurrentPage()">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 2v8m0 0-2.5-2.5M8 10l2.5-2.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 13h10" stroke-linecap="round"/></svg>
        Export CSV
      </button>
    </div>
  </div>

  <!-- Month pagination -->
  <div class="month-strip">
    <button class="ms-arrow" id="ms-prev" onclick="prevMonth()">&#8592;</button>
    <div class="ms-pills">
      <button class="ms-pill" id="mp0"  onclick="setMonth(0)">Jan</button>
      <button class="ms-pill" id="mp1"  onclick="setMonth(1)">Feb</button>
      <button class="ms-pill" id="mp2"  onclick="setMonth(2)">Mar</button>
      <button class="ms-pill" id="mp3"  onclick="setMonth(3)">Apr</button>
      <button class="ms-pill" id="mp4"  onclick="setMonth(4)">May</button>
      <button class="ms-pill" id="mp5"  onclick="setMonth(5)">Jun</button>
      <button class="ms-pill" id="mp6"  onclick="setMonth(6)">Jul</button>
      <button class="ms-pill" id="mp7"  onclick="setMonth(7)">Aug</button>
      <button class="ms-pill" id="mp8"  onclick="setMonth(8)">Sep</button>
      <button class="ms-pill" id="mp9"  onclick="setMonth(9)">Oct</button>
      <button class="ms-pill" id="mp10" onclick="setMonth(10)">Nov</button>
      <button class="ms-pill" id="mp11" onclick="setMonth(11)">Dec</button>
      <button class="ms-pill ms-yr"  id="mpyr" onclick="setMonth(-1)">Year</button>
    </div>
    <button class="ms-arrow" id="ms-next" onclick="nextMonth()">&#8594;</button>
  </div>

  <div id="page-overview">
  <div class="metrics">
    <div class="mc">
      <div class="lbl" style="display:flex;align-items:center">Total MRR<span class="info-btn" onclick="this.classList.toggle('open')" tabindex="0">i<span class="info-tip">Receita mensal recorrente de todas as assinaturas ativas. Inclui mensalistas + anuais ÷ 12, todas as moedas convertidas para USD pela taxa do dia via open.er-api.com.</span></span></div>
      <div class="val" style="color:var(--green)">${metrics["total_mrr"]:,.0f}</div>
      <div class="sub">{metrics["active_subs"]} active subscriptions</div>
    </div>
    <div class="mc">
      <div class="lbl" style="display:flex;align-items:center">Monthly revenue<span class="info-btn" onclick="this.classList.toggle('open')" tabindex="0">i<span class="info-tip">MRR apenas das assinaturas com ciclo mensal. Exclui assinaturas anuais.</span></span></div>
      <div class="val">${metrics["monthly_mrr"]:,.0f}<span style="font-size:13px;font-weight:400;color:var(--text3)">/mo</span></div>
      <div class="sub">{metrics["monthly_count"]} monthly subscribers</div>
    </div>
    <div class="mc">
      <div class="lbl" style="display:flex;align-items:center">ARR<span class="info-btn" onclick="this.classList.toggle('open')" tabindex="0">i<span class="info-tip">Annual Recurring Revenue = MRR × 12. Representa o valor anualizado de toda a base ativa atual, incluindo mensalistas e anuais.</span></span></div>
      <div class="val">${metrics["total_mrr"]*12:,.0f}<span style="font-size:13px;font-weight:400;color:var(--text3)">/yr</span></div>
      <div class="sub">{metrics["annual_count"]} annual + {metrics["monthly_count"]} monthly plans</div>
    </div>
    <div class="mc">
      <div class="lbl" style="display:flex;align-items:center">Recent collected<span class="info-btn" onclick="this.classList.toggle('open')" tabindex="0">i<span class="info-tip">Soma dos pagamentos recebidos nas últimas 24h, convertidos para USD. Fonte: faturas pagas com amount_paid > 0.</span></span></div>
      <div class="val" style="color:{'var(--green)' if today_total>0 else 'var(--text3)'}">{today_total_fmt}</div>
      <div class="sub">{today_count} payment{"s" if today_count != 1 else ""} · since yesterday · USD</div>
    </div>
  </div>

  <div class="row2" style="margin-bottom:1.5rem;grid-template-columns:1fr 1fr 1fr">
    <!-- Expected vs Collected -->
    <div class="card">
      <div class="card-title" style="color:var(--text);display:flex;align-items:center;gap:4px" id="cmp-title">Expected vs Collected<span class="info-btn" onclick="this.classList.toggle('open')" tabindex="0">i<span class="info-tip">Esperado = projeção de billing do mês selecionado (assinaturas ativas). Coletado = faturas pagas com amount_paid > 0 nesse mês, via Invoice.list.</span></span></div>
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
    <!-- Period summary -->
    <div class="card">
      <div class="card-title" style="color:var(--text);display:flex;align-items:center;gap:4px" id="sel-title">Selected period<span class="info-btn" onclick="this.classList.toggle('open')" tabindex="0">i<span class="info-tip">Resumo do período selecionado na barra de meses. Clientes ativos = únicos com todas as assinaturas ativas. Billing this month = com next_inv nesse mês. At risk = MRR mensal de Past due + Unpaid.</span></span></div>
      <div class="kv"><span class="k">Expected revenue</span><span class="v green" id="sel-expected">—</span></div>
      <div class="kv"><span class="k">Active customers</span><span class="v" id="sel-total-active" title="Unique customers with all-active status">—</span></div>
      <div class="kv"><span class="k">Active paying this month</span><span class="v" id="sel-active-count">—</span></div>
      <div class="kv"><span class="k">At risk (problem accounts)</span><span class="v red" id="sel-problem">—</span></div>
    </div>
    <!-- At-risk bar chart card -->
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px">
        <div class="card-title" style="color:var(--text);margin-bottom:0;display:flex;align-items:center;gap:4px">Revenue at risk<span class="info-btn" onclick="this.classList.toggle('open')" tabindex="0">i<span class="info-tip">MRR mensal equivalente de clientes com status Past due ou Unpaid. A barra mostra a progressão mês a mês ao longo de 2026 — útil para avaliar se a inadimplência cresce ou diminui.</span></span></div>
        <span style="font-size:20px;font-weight:700;color:var(--red)" id="risk-amt">—</span>
      </div>
      <div id="risk-bars" style="display:flex;align-items:flex-end;gap:3px;height:64px;margin-bottom:8px"></div>
      <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text3);margin-bottom:10px">
        <span>Jan</span><span>Feb</span><span>Mar</span><span>Apr</span><span>May</span><span>Jun</span>
        <span>Jul</span><span>Aug</span><span>Sep</span><span>Oct</span><span>Nov</span><span>Dec</span>
      </div>
      <div class="kv" style="border-top:0.5px solid var(--border2);padding-top:8px">
        <span class="k">Past due</span><span class="v" id="risk-pastdue" style="color:var(--red)">—</span>
      </div>
      <div class="kv">
        <span class="k">Unpaid</span><span class="v" id="risk-unpaid" style="color:var(--red)">—</span>
      </div>
    </div>
  </div>

  <!-- Volume card -->
  <div class="card" style="margin-bottom:1.5rem" id="vol-card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <div class="card-title" style="color:var(--text);margin-bottom:0;display:flex;align-items:center;gap:4px" id="vol-title">Volume<span class="info-btn" onclick="this.classList.toggle('open')" tabindex="0">i<span class="info-tip">Gross = soma de PaymentIntents succeeded (pagamentos online por cartão). Refunds = reembolsos com status succeeded no mesmo período. Net = Gross − Refunds. Não inclui boleto, wire transfer ou crédito de saldo.</span></span></div>
      <span style="font-size:11px;color:var(--text3)">online card payments</span>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:1rem">
      <div style="background:var(--bg2);border-radius:var(--r);padding:.75rem">
        <div style="font-size:11px;color:var(--text3);margin-bottom:4px;display:flex;align-items:center;gap:5px">
          <span style="width:7px;height:7px;border-radius:50%;background:#639922;flex-shrink:0"></span>Gross
        </div>
        <div style="font-size:18px;font-weight:500;color:var(--text)" id="vol-gross">—</div>
        <div style="font-size:11px;color:var(--text3);margin-top:2px" id="vol-gross-n"></div>
      </div>
      <div style="background:var(--bg2);border-radius:var(--r);padding:.75rem">
        <div style="font-size:11px;color:var(--text3);margin-bottom:4px;display:flex;align-items:center;gap:5px">
          <span style="width:7px;height:7px;border-radius:50%;background:#E24B4A;flex-shrink:0"></span>Refunds
        </div>
        <div style="font-size:18px;font-weight:500;color:var(--red)" id="vol-refunds">—</div>
        <div style="font-size:11px;color:var(--text3);margin-top:2px" id="vol-refunds-n"></div>
      </div>
      <div style="background:var(--bg2);border-radius:var(--r);padding:.75rem">
        <div style="font-size:11px;color:var(--text3);margin-bottom:4px;display:flex;align-items:center;gap:5px">
          <span style="width:7px;height:7px;border-radius:50%;background:#185FA5;flex-shrink:0"></span>Net
        </div>
        <div style="font-size:18px;font-weight:500;color:var(--blue)" id="vol-net">—</div>
        <div style="font-size:11px;color:var(--text3);margin-top:2px" id="vol-pct"></div>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;gap:7px">
      <div style="display:grid;grid-template-columns:60px 1fr 72px;gap:8px;align-items:center">
        <span style="font-size:11px;color:var(--text3);text-align:right">Gross</span>
        <div style="height:7px;background:var(--bg2);border-radius:4px;overflow:hidden">
          <div id="vol-bar-gross" style="height:100%;width:100%;background:#639922;border-radius:4px;transition:width .4s"></div>
        </div>
        <span style="font-size:12px;font-weight:500;color:var(--text)" id="vol-bar-gross-lbl"></span>
      </div>
      <div style="display:grid;grid-template-columns:60px 1fr 72px;gap:8px;align-items:center">
        <span style="font-size:11px;color:var(--text3);text-align:right">Refunds</span>
        <div style="height:7px;background:var(--bg2);border-radius:4px;overflow:hidden">
          <div id="vol-bar-refunds" style="height:100%;width:0%;background:#E24B4A;border-radius:4px;transition:width .4s"></div>
        </div>
        <span style="font-size:12px;color:var(--red)" id="vol-bar-refunds-lbl"></span>
      </div>
      <div style="display:grid;grid-template-columns:60px 1fr 72px;gap:8px;align-items:center">
        <span style="font-size:11px;color:var(--text3);text-align:right">Net</span>
        <div style="height:7px;background:var(--bg2);border-radius:4px;overflow:hidden">
          <div id="vol-bar-net" style="height:100%;width:0%;background:#185FA5;border-radius:4px;transition:width .4s"></div>
        </div>
        <span style="font-size:12px;font-weight:500;color:#185FA5" id="vol-bar-net-lbl"></span>
      </div>
    </div>
  </div>

  <div class="card" style="margin-bottom:1.5rem">
    <div class="card-title" style="color:var(--text)">Recent payments <span style="font-weight:400;font-size:10px;color:var(--text3);text-transform:none;letter-spacing:0">(last 24h · USD equiv.)</span></div>
    {"<div class='inv-wrap'><table class='inv-table'><thead><tr><th>Customer</th><th class='r'>Amount</th><th>Time</th></tr></thead><tbody>" + today_rows_html + "</tbody></table></div>" if today_invoices else "<div class='empty'>No payments in the last 24h</div>"}
  </div>

  <div class="tbl-section">
    <div class="tbl-header">
      <div class="card-title" style="color:var(--text)" id="tbl-title" style="margin-bottom:0">All customers</div>
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
        <thead><tr id="tbl-head">
          <th style="width:28%;cursor:pointer;user-select:none" onclick="setSortCol(0)">Customer <span id="sh0"></span></th>
          <th style="width:9%;cursor:pointer;user-select:none" onclick="setSortCol(6)">Country <span id="sh6"></span></th>
          <th style="width:11%;cursor:pointer;user-select:none" onclick="setSortCol(7)">Type <span id="sh7"></span></th>
          <th style="width:11%;cursor:pointer;user-select:none" onclick="setSortCol(1)">Status <span id="sh1"></span></th>
          <th style="width:14%;cursor:pointer;user-select:none" onclick="setSortCol(5)">Next invoice <span id="sh5"></span></th>
          <th style="width:12%;cursor:pointer;user-select:none" class="r col-annual" onclick="setSortCol(8)">Annual total <span id="sh8"></span></th>
          <th style="width:12%;cursor:pointer;user-select:none" class="r" onclick="setSortCol(3)">Base amount <span id="sh3"></span></th>
          <th style="width:8%;cursor:pointer;user-select:none" onclick="setSortCol(2)">Interval <span id="sh2"></span></th>
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

  </div><!-- /page-overview -->

  <!-- Analytics page -->
  <div id="page-analytics" style="display:none">
    <div class="analytics-grid" style="margin-bottom:1.5rem">
      <div class="card">
        <div class="card-title" style="color:var(--text);display:flex;align-items:center;gap:4px">Customers by type<span class="info-btn" onclick="this.classList.toggle('open')" tabindex="0">i<span class="info-tip">Distribuição de clientes ativos por tipo, baseada no campo CompanyType do HubSpot (649 mapeamentos por Stripe Customer ID). Inclui apenas status Active.</span></span></div>
        <div id="pie-count" style="display:flex;flex-direction:column;align-items:center;gap:16px"></div>
      </div>
      <div class="card">
        <div class="card-title" style="color:var(--text);display:flex;align-items:center;gap:4px">MRR by type<span class="info-btn" onclick="this.classList.toggle('open')" tabindex="0">i<span class="info-tip">MRR mensal por tipo de cliente, calculado por assinatura (não por cliente) para tratar corretamente intervalos mistos. Soma deve ser igual ao Total MRR do Overview.</span></span></div>
        <div id="pie-mrr" style="display:flex;flex-direction:column;align-items:center;gap:16px"></div>
      </div>
    </div>

    <div class="card" style="margin-bottom:1.5rem">
      <div class="card-title" style="color:var(--text);display:flex;align-items:center;gap:4px">Revenue &amp; customers by country<span class="info-btn" onclick="this.classList.toggle('open')" tabindex="0">i<span class="info-tip">País identificado pelo address.country do cliente no Stripe. Quando ausente, inferido pela moeda da assinatura (ex: BRL → BR). MRR = equivalente mensal, incluindo anuais ÷ 12.</span></span></div>
      <div style="overflow-x:auto;border-radius:var(--r);border:0.5px solid var(--border2)">
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="background:var(--bg2)">
              <th style="text-align:left;padding:8px 14px;font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.04em;border-bottom:0.5px solid var(--border2)">Country</th>
              <th style="text-align:right;padding:8px 14px;font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.04em;border-bottom:0.5px solid var(--border2)">Customers</th>
              <th style="text-align:right;padding:8px 14px;font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.04em;border-bottom:0.5px solid var(--border2)">Active</th>
              <th style="text-align:left;padding:8px 14px;font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.04em;border-bottom:0.5px solid var(--border2);min-width:140px">MRR</th>
              <th style="text-align:right;padding:8px 14px;font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.04em;border-bottom:0.5px solid var(--border2)">Share</th>

            </tr>
          </thead>
          <tbody id="country-table"></tbody>
        </table>
      </div>
    </div>
  </div>

</div>
<script>
const MONTHS=["Jan 2026","Feb 2026","Mar 2026","Apr 2026","May 2026","Jun 2026","Jul 2026","Aug 2026","Sep 2026","Oct 2026","Nov 2026","Dec 2026"];
const MO_SHORT=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const D={rows_js}.filter(r=>r[1]!=="Cancelled");
const COLLECTED={collected_js};
const MRR_BY_TYPE={mrr_by_type_js};
const PROBLEM_TOTALS={problem_tot_js};
const GROSS_VOL={gross_js};
const REFUND_VOL={refunds_js};
const NET_VOL={net_js};
const BC={{"Active":"b-active","Past due":"b-pastdue","Unpaid":"b-unpaid"}};
const fmt=v=>v===0?"—":(v<0?"-":"")+new Intl.NumberFormat("en-US",{{style:"currency",currency:"USD",maximumFractionDigits:0}}).format(Math.abs(v));
const fmtS=v=>Math.abs(v)>=1000?(v<0?"-":"")+"$"+(Math.abs(v)/1000).toFixed(1)+"k":"$"+Math.round(v);

let mi=4,pg=1,sf="all"; // mi: 0-11=Jan-Dec, -1=Year; default May (index 4)
const PS=15;

function byStatus(){{
  const f=sf;
  return D.filter(r=>{{
    if(f==="all") return true;
    if(f==="Active") return r[1]==="Active";
    if(f==="problem") return r[1]==="Past due"||r[1]==="Unpaid";

    return true;
  }});
}}

function prevMonth(){{if(mi===-1)setMonth(11);else if(mi>0)setMonth(mi-1);}}
function nextMonth(){{if(mi===11)setMonth(-1);else if(mi<11)setMonth(mi+1);}}

function flag(c){{if(!c||c.length!==2)return"";return String.fromCodePoint(c.charCodeAt(0)+127397)+String.fromCodePoint(c.charCodeAt(1)+127397);}}

function setMonth(i){{
  mi=i;
  const isYr=mi===-1;
  const label=isYr?"Full Year 2026":MONTHS[mi];
  for(let c=0;c<12;c++){{const el=document.getElementById("mp"+c);if(el)el.classList.toggle("active",c===mi);}}
  const yr=document.getElementById("mpyr");if(yr)yr.classList.toggle("active",isYr);
  if(document.getElementById("cmp-title")) document.getElementById("cmp-title").textContent="Expected vs Collected — "+label;
  if(document.getElementById("sel-title")) document.getElementById("sel-title").textContent=label;
  if(document.getElementById("tbl-title")) document.getElementById("tbl-title").textContent=isYr?"All customers":"Customers — "+label;
  if(document.getElementById("tbl-hint")) document.getElementById("tbl-hint").textContent=isYr?"Showing all customers — Jan–Dec 2026":"Customers with expected revenue in "+label;
  document.querySelectorAll(".col-annual").forEach(el=>el.style.display=isYr?"none":"");
  updateAll();
}}

function updateVolCard(){{
  const v={{
    gross:   mi>=0?GROSS_VOL[mi]:GROSS_VOL.reduce((s,x)=>s+x,0),
    refunds: mi>=0?REFUND_VOL[mi]:REFUND_VOL.reduce((s,x)=>s+x,0),
    net:     mi>=0?NET_VOL[mi]:NET_VOL.reduce((s,x)=>s+x,0),
  }};
  const label=mi===-1?"Full Year 2026":MONTHS[mi];
  if(document.getElementById("vol-title"))
    document.getElementById("vol-title").textContent="Volume — "+label;
  if(!document.getElementById("vol-gross")) return;
  const g=v.gross,r=v.refunds,n=v.net;
  const pct=g>0?((n/g)*100).toFixed(1):"—";
  document.getElementById("vol-gross").textContent=g>0?fmt(g):"—";
  document.getElementById("vol-refunds").textContent=r>0?"-"+fmtS(r):"—";
  document.getElementById("vol-net").textContent=n>0?fmt(n):"—";
  document.getElementById("vol-pct").textContent=g>0?pct+"% of gross":"";
  document.getElementById("vol-bar-gross-lbl").textContent=g>0?fmtS(g):"—";
  document.getElementById("vol-bar-refunds-lbl").textContent=r>0?"-"+fmtS(r):"—";
  document.getElementById("vol-bar-net-lbl").textContent=n>0?fmtS(n):"—";
  const maxW=g||1;
  document.getElementById("vol-bar-gross").style.width="100%";
  document.getElementById("vol-bar-refunds").style.width=Math.min(100,(r/maxW)*100).toFixed(1)+"%";
  document.getElementById("vol-bar-net").style.width=Math.min(100,(n/maxW)*100).toFixed(1)+"%";
}}

function updateAll(){{
  sf=document.getElementById("flt").value;
  updateSelCard();
  updateCmpCard();
  updateVolCard();
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
  const totalActive=D.filter(r=>r[1]==="Active").length;
  document.getElementById("sel-total-active").textContent=totalActive+" customers";
  document.getElementById("sel-expected").textContent=expected>0?fmt(expected):"—";
  document.getElementById("sel-active-count").textContent=activeCount+" customers";
  // At-risk calculations
  const pastDueRows=D.filter(r=>r[1]==="Past due");
  const unpaidRows=D.filter(r=>r[1]==="Unpaid");
  const pdAmt=pastDueRows.reduce((s,r)=>s+(r[2]==="Annual"?r[3]/12:r[3]),0);
  const unpAmt=unpaidRows.reduce((s,r)=>s+(r[2]==="Annual"?r[3]/12:r[3]),0);
  document.getElementById("sel-problem").textContent=(pdAmt+unpAmt)>0?"-"+fmtS(pdAmt+unpAmt):problems.length+" accounts";
  // Current-month at-risk from PROBLEM_TOTALS (matches projection logic)
  const riskCur=pdAmt+unpAmt; // total monthly MRR at risk = matches breakdown
  if(document.getElementById("risk-amt")){{
    document.getElementById("risk-amt").textContent=riskCur>0?"-"+fmtS(riskCur):"—";
    // Draw monthly bar chart
    const maxV=Math.max(...PROBLEM_TOTALS,1);
    document.getElementById("risk-bars").innerHTML=PROBLEM_TOTALS.map((v,i)=>{{
      const h=Math.round((v/maxV)*56)+4;
      const isActive=i===mi;
      const clr=isActive?"var(--red)":"rgba(220,38,38,0.3)";
      const lbl=fmtS(v);
      return `<div title="${{MO_SHORT[i]}}: ${{lbl}}" style="flex:1;height:${{h}}px;background:${{clr}};border-radius:3px 3px 0 0;cursor:default;position:relative;transition:all .2s">
        ${{isActive?`<span style="position:absolute;bottom:calc(100% + 2px);left:50%;transform:translateX(-50%);font-size:9px;color:var(--red);white-space:nowrap">${{lbl}}</span>`:""}}</div>`;
    }}).join("");
    document.getElementById("risk-pastdue").textContent=pdAmt>0?fmtS(pdAmt)+" · "+pastDueRows.length+" cust.":"—";
    document.getElementById("risk-unpaid").textContent=unpAmt>0?fmtS(unpAmt)+" · "+unpaidRows.length+" cust.":"—";
  }}
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

let sortCol=3,sortDir=-1; // default: base amount descending

function annualVal(r){{return r[2]==="Annual"?r[3]:r[3]*12;}}

function setSortCol(col){{
  if(sortCol===col){{sortDir*=-1;}}else{{sortCol=col;sortDir=col===3||col===8?-1:1;}}
  // Update header indicators
  [0,1,2,3,5,6,7,8].forEach(c=>{{
    const el=document.getElementById("sh"+c);
    if(el) el.textContent=sortCol===c?(sortDir===1?" ↑":" ↓"):"";
    const th=el&&el.parentElement;
    if(th) th.style.color=sortCol===c?"var(--text)":"";
  }});
  renderTable();
}}

// Parse "Jun 15, 2026" → month index 0-11
function invMonth(dateStr){{
  try{{const d=new Date(dateStr);if(isNaN(d))return -1;
    if(d.getFullYear()===2026)return d.getMonth();
    if(d.getFullYear()===2027)return 12; // next year, outside window
    return -1;}}catch(e){{return -1;}}
}}

function getFiltered(){{
  const q=document.getElementById("search").value.toLowerCase();
  const base=byStatus();
  let byM;
  if(mi>=0){{
    // Month view: show customers whose next invoice falls in this month
    // This ensures each month shows a distinct, relevant set of customers
    byM=base.filter(r=>{{
      const nim=invMonth(r[5]);
      if(nim===mi) return true; // next invoice is this month ✓
      // Also include annual subs whose renewal is this month (may have already renewed)
      if(r[2]==="Annual"&&r[4][mi]>0) return true;
      return false;
    }});
    // If no matches (e.g. past month where all next_inv have moved forward),
    // fall back to projection-based filter
    if(byM.length===0) byM=base.filter(r=>r[4][mi]>0);
  }}else{{
    byM=base; // Year: show all
  }}
  const filtered=byM.filter(r=>!q||r[0].toLowerCase().includes(q));
  return filtered.slice().sort((a,b)=>{{
    let va,vb;
    if(sortCol===8){{va=annualVal(a);vb=annualVal(b);}}
    else if(sortCol===3){{va=a[3];vb=b[3];}}
    else{{va=String(a[sortCol]||"").toLowerCase();vb=String(b[sortCol]||"").toLowerCase();
      return sortDir*va.localeCompare(vb);}}
    return sortDir*(vb-va);
  }});
}}

function renderTable(){{pg=1;_render();}}
function go(d){{const tp=Math.ceil(getFiltered().length/PS);pg=Math.max(1,Math.min(tp,pg+d));_render();}}
const TYPE_COLORS={{"Retailer":"#639922","Manufacturer":"#854F0B","Ecommerce":"#635BFF","Distributor":"#A32D2D","Installer":"#185FA5"}};
function typePill(t,n){{const c=TYPE_COLORS[t]||"#888780";return`<span style="display:inline-flex;align-items:center;gap:3px;font-size:11px;padding:2px 7px;border-radius:20px;background:${{c}}22;color:${{c}}">${{t}}${{n?'<span style="opacity:.7">'+n+'</span>':''}}</span>`;}}

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
      <td>${{r[7]?typePill(r[7],""): '<span style="color:var(--text3);font-size:11px">—</span>'}}</td>
      <td><span class="badge ${{BC[r[1]]||"b-unpaid"}}">${{r[1]}}</span></td>
      <td style="font-size:12px;color:${{prob?"var(--red)":"var(--text2)"}};font-weight:${{prob?500:400}}">${{r[5]||"—"}}</td>
      <td class="r col-annual" style="color:var(--text2)">${{annualTotal>0?fmt(annualTotal):"—"}}</td>
      <td class="r" style="color:var(--text2)">$${{r[3].toLocaleString()}}</td>
      <td><span class="freq">${{r[2]}}</span></td>
    </tr>`;
  }}).join("");
}}


// CSV export helpers
const NL=String.fromCodePoint(10);
const CTRY_NAMES={{"US":"United States","AU":"Australia","BR":"Brazil","ZA":"South Africa","GB":"United Kingdom","NL":"Netherlands","AR":"Argentina","MX":"Mexico","JP":"Japan","SG":"Singapore","DK":"Denmark","IT":"Italy","NZ":"New Zealand","CA":"Canada","DE":"Germany","FR":"France","ES":"Spain","PT":"Portugal","IL":"Israel","MA":"Morocco","BE":"Belgium","CZ":"Czech Republic","AT":"Austria","CH":"Switzerland","SE":"Sweden","NO":"Norway","FI":"Finland","PL":"Poland","CO":"Colombia","CL":"Chile","IN":"India","AE":"UAE","ID":"Indonesia","MY":"Malaysia","TH":"Thailand","PE":"Peru","UY":"Uruguay"}};
function ctryName(c){{return CTRY_NAMES[c]||(c||"Unknown");}}
function _dl(blob,fname){{const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=fname;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1e3);}}
function _csv(hdrs,rows){{const q=v=>'"'+String(v).split('"').join('""')+'"';return new Blob([[hdrs,...rows].map(r=>r.map(q).join(',')).join(NL)],{{type:'text/csv'}});}}
function exportCurrentPage(){{document.getElementById('page-analytics').style.display!=='none'?exportAnalytics():exportOverview();}}
function exportOverview(){{
  const mo=mi===-1?'FullYear2026':MONTHS[mi].replace(' ','');
  const rows=getFiltered().map(r=>{{const ann=r[2]==='Annual'?r[3]:r[3]*12;return [r[0],r[1],r[2],r[3],ann,r[5]||'',ctryName(r[6]||''),r[7]||''];}});
  _dl(_csv(['Customer','Status','Interval','Base USD','Annual USD','Next Invoice','Country','Type'],rows),'floori-customers-'+mo+'.csv');
}}
function exportAnalytics(){{
  const byC={{}};D.forEach(r=>{{const k=r[6]||'Unknown';const m=r[1]==='Active'?(r[2]==='Annual'?r[3]/12:r[3]):0;if(!byC[k])byC[k]={{m:0,n:0,a:0}};byC[k].m+=m;byC[k].n++;if(r[1]==='Active')byC[k].a++;}});
  const tot=Object.values(byC).reduce((s,v)=>s+v.m,0);
  const rows=Object.entries(byC).sort((a,b)=>b[1].m-a[1].m).map(([c,v])=>[c,ctryName(c),v.n,v.a,v.m.toFixed(2),tot>0?((v.m/tot)*100).toFixed(1):'0.0']);
  _dl(_csv(['Code','Country','Customers','Active','MRR/mo','Share%','Top Type'],rows),'floori-analytics-by-country.csv');
}}

(function(){{
  const now=new Date();
  const mi=now.getFullYear()===2026?now.getMonth():(now.getFullYear()>2026?11:0);
  setMonth(mi);
}})();

// ── Tab navigation ────────────────────────────────────────────────────────────
function switchTab(tab){{
  document.getElementById("page-overview").style.display = tab==="overview"?"":"none";
  document.getElementById("page-analytics").style.display = tab==="analytics"?"":"none";
  document.getElementById("tab-overview").classList.toggle("active", tab==="overview");
  document.getElementById("tab-analytics").classList.toggle("active", tab==="analytics");
  if(tab==="analytics") renderAnalytics();
}}

// ── Analytics rendering ───────────────────────────────────────────────────────
// ── Pie chart ────────────────────────────────────────────────────────────────
function _makePie(containerId, data, fmtVal){{
  const el=document.getElementById(containerId);
  if(!el)return;
  const total=data.reduce((s,d)=>s+d.v,0);
  if(!total){{el.innerHTML='<span style="color:var(--text3);font-size:13px">No data</span>';return;}}
  const cx=90,cy=90,r=80,size=180;
  let angle=-Math.PI/2;
  let slices='';
  data.forEach(d=>{{
    const pct=d.v/total;
    const a=pct*2*Math.PI;
    const x1=cx+r*Math.cos(angle),y1=cy+r*Math.sin(angle);
    const x2=cx+r*Math.cos(angle+a),y2=cy+r*Math.sin(angle+a);
    const large=a>Math.PI?1:0;
    if(pct>0.001){{
      slices+=`<path d="M${{cx}},${{cy}} L${{x1.toFixed(2)}},${{y1.toFixed(2)}} A${{r}},${{r}} 0 ${{large}},1 ${{x2.toFixed(2)}},${{y2.toFixed(2)}} Z"
        fill="${{d.c}}" stroke="var(--bg)" stroke-width="1.5">
        <title>${{d.l}}: ${{fmtVal(d.v)}} (${{(pct*100).toFixed(1)}}%)</title></path>`;
    }}
    angle+=a;
  }});
  const legend=data.map(d=>{{
    const pct=(d.v/total*100).toFixed(1);
    return `<div style="display:flex;align-items:center;gap:8px;font-size:12px">
      <span style="width:10px;height:10px;border-radius:2px;background:${{d.c}};flex-shrink:0"></span>
      <span style="flex:1;color:var(--text2)">${{d.l}}</span>
      <span style="color:var(--text);font-weight:500">${{fmtVal(d.v)}}</span>
      <span style="color:var(--text3);min-width:38px;text-align:right">${{pct}}%</span>
    </div>`;
  }}).join('');
  el.innerHTML=`<svg viewBox="0 0 ${{size}} ${{size}}" width="${{size}}" height="${{size}}" style="overflow:visible">${{slices}}</svg>
    <div style="width:100%;max-width:240px;display:flex;flex-direction:column;gap:6px">${{legend}}</div>`;
}}

function renderAnalytics(){{
  const all=D;
  const byCtry={{}};
  all.forEach(r=>{{
    const code=r[6]||"";
    const k=code||"Unknown";
    const mrr=r[1]==="Active"?(r[2]==="Annual"?r[3]/12:r[3]):0;
    const t=(r[7]||"").trim();
    if(!byCtry[k]) byCtry[k]={{mrr:0,count:0,active:0}};
    byCtry[k].mrr+=mrr;
    byCtry[k].count+=1;
    if(r[1]==="Active") byCtry[k].active+=1;
  }});

  const sorted=Object.entries(byCtry).sort((a,b)=>b[1].mrr-a[1].mrr||b[1].count-a[1].count);
  const maxMrr=Math.max(...sorted.map(([,v])=>v.mrr))||1;
  const totalMrr=sorted.reduce((s,[,v])=>s+v.mrr,0);
  const totalCust=all.length||1;

  // MRR by country
  const mrrHtml=sorted.map(([code,v])=>{{
    const pct=Math.round((v.mrr/maxMrr)*100);
    const share=totalMrr>0?Math.round(v.mrr/totalMrr*100):0;
    const mrrStr=v.mrr>0?fmtS(v.mrr)+"/mo":"—";
    return `<div class="ctry-row">
      <span class="ctry-name">${{ctryName(code)}}</span>
      <div class="ctry-bar-wrap"><div class="ctry-bar-fill" style="width:${{pct}}%"></div></div>
      <span class="ctry-val" style="${{v.mrr>0?"color:var(--green);font-weight:500":"color:var(--text3)"}}">${{mrrStr}}</span>
      <span class="ctry-count">${{share>0?share+"%":"—"}}</span>
    </div>`;
  }}).join("");
  const tableHtml=sorted.map(([code,v],idx)=>{{
    const barW=totalMrr>0?Math.round((v.mrr/maxMrr)*100):0;
    const share=totalMrr>0?((v.mrr/totalMrr)*100).toFixed(1):0;
    const mrrStr=v.mrr>0?fmtS(v.mrr)+"/mo":"—";
    const bg=idx%2===0?"":"background:var(--bg2)";
    return `<tr style="border-bottom:0.5px solid var(--border2);${{bg}}">
      <td style="padding:9px 14px;font-weight:500">${{ctryName(code)}}</td>
      <td style="padding:9px 14px;text-align:right">${{v.count}}</td>
      <td style="padding:9px 14px;text-align:right;color:var(--green)">${{v.active}}</td>
      <td style="padding:9px 14px">
        <div style="display:flex;align-items:center;gap:8px">
          <div style="flex:1;height:6px;background:var(--bg2);border-radius:3px;overflow:hidden;max-width:100px">
            <div style="height:100%;width:${{barW}}%;background:var(--gbar);border-radius:3px"></div>
          </div>
          <span style="font-size:12px;font-variant-numeric:tabular-nums;color:${{v.mrr>0?"var(--green)":"var(--text3)"}};font-weight:${{v.mrr>0?500:400}}">${{mrrStr}}</span>
        </div>
      </td>
      <td style="padding:9px 14px;text-align:right;color:var(--text3);font-size:12px">${{v.mrr>0?share+"%":"—"}}</td>
    </tr>`;
  }}).join("");
  document.getElementById("country-table").innerHTML=tableHtml||"<tr><td colspan='5' style='padding:2rem;text-align:center;color:var(--text3)'>No data</td></tr>";

  // ── Pie charts by customer type — Active only (matches MRR card) ──────────
  const TC={{"Retailer":"#639922","Manufacturer":"#854F0B","Ecommerce":"#635BFF",
             "Distributor":"#A32D2D","Installer":"#185FA5","Unclassified":"#888780"}};
  const byType={{}};
  // Customer count by type — Active only
  D.filter(r=>r[1]==="Active").forEach(r=>{{
    const t=(r[7]||"").trim()||"Unclassified";
    if(!byType[t])byType[t]={{n:0}};
    byType[t].n++;
  }});
  const typeSorted=Object.entries(byType).sort((a,b)=>b[1].n-a[1].n);
  const pieCount=typeSorted.map(([t,v])=>{{return{{l:t,v:v.n,c:TC[t]||"#888780"}}}});
  // MRR by type — from Python (per-subscription, interval-correct)
  const mrrEntries=Object.entries(MRR_BY_TYPE).sort((a,b)=>b[1]-a[1]);
  const pieMrr=mrrEntries.map(([t,v])=>{{return{{l:t,v:Math.round(v),c:TC[t]||"#888780"}}}});
  _makePie("pie-count",pieCount,v=>v+" cust.");
  _makePie("pie-mrr",pieMrr,v=>"$"+v.toLocaleString()+"/mo");
}}
</script>
</body>
</html>"""

if __name__ == "__main__":
    import sys
    errors = []

    print("=== Floori Dashboard Update ===")
    print("Started: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    # ── 1. Fetch subscriptions ──────────────────────────────────────────────
    print("\n[1/6] Fetching subscriptions from Stripe...")
    try:
        subs = fetch_all_subscriptions()
        print("  OK " + str(len(subs)) + " subscriptions fetched")
    except Exception as e:
        print("  FATAL: " + str(e), file=sys.stderr)
        sys.exit(1)

    # ── 2. Load FX rates ────────────────────────────────────────────────────
    print("\n[2/6] Loading FX rates...")
    try:
        _load_fx_rates()
        print("  OK " + str(len(_FX_RATES)) + " currencies loaded")
    except Exception as e:
        print("  WARNING: FX rates failed (" + str(e) + ") — non-USD amounts may be 0")
        errors.append("FX rates: " + str(e))

    status_counts = {}
    for s in subs:
        label = stripe_status_to_label(s.status)
        status_counts[label] = status_counts.get(label, 0) + 1
    print("  Status breakdown: " + str(dict(sorted(status_counts.items()))))

    # ── 3. Build rows + metrics ─────────────────────────────────────────────
    print("\n[3/6] Building customer rows...")
    try:
        rows = build_rows(subs)
        print("  OK " + str(len(rows)) + " unique customers")
    except Exception as e:
        print("  FATAL: " + str(e), file=sys.stderr)
        sys.exit(1)

    totals, active_tot, problem_tot = compute_totals(rows)

    print("\n[4/6] Computing subscription metrics...")
    try:
        metrics = compute_subscription_metrics(subs)
        print("  OK MRR $" + f"{metrics['total_mrr']:,.0f}" + " | ARR $" + f"{metrics['total_mrr']*12:,.0f}")
        print("     Active subs: " + str(metrics['active_subs']) +
              " | Monthly: " + str(metrics['monthly_count']) +
              " | Annual: " + str(metrics['annual_count']))
    except Exception as e:
        print("  FATAL: " + str(e), file=sys.stderr)
        sys.exit(1)

    # ── 4. Recent invoices + collected cache ─────────────────────────────────
    print("\n[5/6] Fetching invoices and collected data...")
    try:
        today_invoices = fetch_today_invoices(subs)
        print("  OK " + str(len(today_invoices)) + " payment(s) in last 24h")
    except Exception as e:
        print("  WARNING: today invoices failed: " + str(e))
        today_invoices = []
        errors.append("Today invoices: " + str(e))

    try:
        monthly_collected = fetch_monthly_collected()
        rounded = ["$" + f"{round(x):,}" for x in monthly_collected]
        print("  OK collected by month: " + str(rounded))
    except Exception as e:
        print("  WARNING: monthly collected failed: " + str(e))
        monthly_collected = [0.0] * 12
        errors.append("Monthly collected: " + str(e))

    try:
        monthly_gross, monthly_refunds, monthly_net = fetch_monthly_volume()
        print("  OK volume by month: gross=" + str(["$"+f"{round(x):,}" for x in monthly_gross]))
    except Exception as e:
        print("  WARNING: monthly volume failed: " + str(e))
        monthly_gross = monthly_refunds = monthly_net = [0.0] * 12
        errors.append("Monthly volume: " + str(e))

    # ── 5. Render + write ────────────────────────────────────────────────────
    print("\n[6/6] Rendering dashboard...")
    synced = datetime.now(timezone.utc).strftime("%b %d, %Y at %H:%M UTC")
    try:
        html = render_html(rows, totals, active_tot, problem_tot, synced, metrics, today_invoices, monthly_collected, monthly_gross, monthly_refunds, monthly_net)
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("  OK index.html written (" + f"{len(html):,}" + " bytes)")
    except Exception as e:
        print("  FATAL: render failed: " + str(e), file=sys.stderr)
        sys.exit(1)

    print("\n=== Done: " + synced + " ===")
    if errors:
        print("Warnings (" + str(len(errors)) + "):")
        for err in errors:
            print("  - " + err)
    else:
        print("All steps completed successfully")
