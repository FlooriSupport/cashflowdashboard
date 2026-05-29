"""
update_dashboard.py
Fetches live subscription data from Stripe and regenerates index.html.
Runs via GitHub Actions every weekday at 9:30 AM BRT.
"""

import os, json, stripe
from datetime import datetime, timezone

stripe.api_key = os.environ["STRIPE_API_KEY"]

# ── Email → customer name mapping (from Floori CSV) ─────────────────────────
EMAIL_TO_NAME = {
    "afshin@unitexint.com": "The Trustee for THE NEJADIRAN FAMILY TRUST",
    "dov@carmelgroup.co.il": "Carmel Floor",
    "atheer@carrim.co.za": "K Carrim Holdings Pty Ltd",
    "eugene@uacarpet.com.sg": "Heritage Carpets",
    "nick@garagefloorcoating.com": "Garage Floor Coating",
    "filip@tapijt.com": "Tapijten Demuynck",
    "mariana.lisboa@indusparquet.com.br": "Indusparquet",
    "contact@everfloor.com.au": "VBL Import Pty Ltd",
    "jason@americanremodeling.net": "Jason Larsen",
    "johan.wingner@bona.com": "Bona US",
    "info@koremanmaastricht.nl": "Koreman Exclusive Carpets",
    "paz.sanmillan@uniber.com.ar": "Supermat",
    "fortressfloorsofmn@gmail.com": "Fortress Floors of MN",
    "jrayala@armorconcretecoatings.com": "Angelo A Ayala Jr",
    "chelseas@motorcityfloorsandcoatings.com": "Robert Falls",
    "billy@paintanddecorate.com.au": "Tony Isgrove's Paint and Decorate",
    "info@toughfloors.com.au": "Tough Floors Australia",
    "accounts@allgrind.com.au": "All Grind",
    "cl@jti-gulv.dk": "Jti Gulventreprise",
    "alexj@emonster.ca": "SHOUGUO JIAO",
    "info@granicreteaustralia.com.au": "Granicrete Australia",
    "brian@encoregroupnj.com": "603 Epoxy",
    "chad.paulson@twincityepoxydocs.com": "Chad Paulson",
    "hello@agcnz.co.nz": "Affordable Garage Carpet",
    "jessica@rugsforgood.com.au": "Rugs for Good Pty LTD",
    "contato@tapetah.com.br": "Tapetah",
    "denis.staudt@herval.com.br": "Global Distribuição de Bens de Consumo",
    "quickresponsefloorcoatings@gmail.com": "Cassandra Koprucu",
    "tim@randswoodflooring.com": "Randswood Flooring",
    "alex@scicoatings.com": "SCI Coatings",
    "nleonhardt@pisosalemanes.com": "The Carpet Company",
    "R.martin@niazi.com.br": "NIAZI CHOHFI",
    "marilia@koord.com.br": "Koord Creativeloom",
    "camila@epoxynetwork.com": "Camila Ordonez",
    "amanda.arsenault@pravadafloors.com": "Pravada",
    "alex@tsrconcretecoatings.com": "Alexander Marck",
    "info@acsento.com": "Acsento",
    "contact@triff.com": "Triff",
    "dev@originate.ie": "Originate",
    "ali@finalspecs.com": "Final Specs Flooring",
    "roni@viastar.com.br": "ViaStar",
    "James@tendadostapetes.com.br": "Tenda dos Tapetes",
    "jennifer.berry@staufusa.com": "Stauf USA",
    "lalvarado@dicsamexico.com.mx": "LA DISTRIBUIDORA DE CASIMIRES",
    "daniele.colcelli@stile.com": "Stile Società Cooperativa",
    "MARKETING@MARBLELIFE.COM": "MARBLELIFE",
    "sophiel@usmills.com": "Sophie Lupien",
    "suzuki-kei@tajima.co.jp": "TAJIMA ROOFING",
    "info@bijan.com.au": "Exclusive Rugs By Bijan",
    "emanuelnoriega@edificor.com.ar": "EDIFICOR S.R.L",
    "shelley@eva-last.com": "Eva-last Hong Kong",
    "info@vanheugtentapijttegels.nl": "Van Heugten Tapijtegels BV",
    "marco@bestwoolcarpets.com": "Best Wool Carpets",
    "carolkeese@carolinaaircare.com": "Carolina Air Care",
    "josefina.cohenp@gmail.com": "Consorcio Persa",
    "suzana@bdesign.com.br": "S W Gomes de Barros",
    "lucas.andrade@luzzo.com.br": "Luzzo Revestimentos",
    "israel.dias@quero-quero.com.br": "LOJAS QUERO-QUERO",
    "daniel.felix@rcpisos.com.br": "ATELIE PISOS",
    "mvarela@cerronegro.com.ar": "CANTERAS CERRO NEGRO",
    "abigail@double.online": "Terra Enterprises",
    "sina@iconicrugs.com.au": "Iconic Rugs",
    "pamela.novak@jetrockinc.com": "JetRock Inc",
    "rich@garageflooringpros.com": "Rich Arriaga",
    "e-commerce@kapazi.com.br": "Kapazi",
    "pisobelo@pisobelo.com.br": "Piso Belo",
    "info@iowaepoxy.com": "William A George",
    "abraham.rafael.gc@hotmail.com": "EDNA VIANNEY GARCIA CUEVAS",
    "Danielle.vieira@floori.io": "Cartacho Tapetes",
    "info@granitestateepoxy.com": "Bryan Coulonbe",
    "Tim@epoxyfloorsnmore.com": "Epoxy Floors N More",
    "ron@superiorgarageusa.com": "Superior Garage Flooring",
    "connorschupbach@gmail.com": "Accu-Seal LLC",
    "opusrenovation22@gmail.com": "Opus Renovation",
    "mix@coatingdesigns.com": "Coatingdesigns.com",
    "protouchcoating@gmail.com": "Pro Touch Coating",
    "waltertwrocha@gmail.com": "Quality Floor",
    "rhys@diamondfloorco.com": "Diamond Floor Co.",
    "terry@tlcec.com.au": "TLC Epoxy Coatings",
    "madisoncoatingscompany@gmail.com": "Madison Coatings",
    "joe@lnsconcretecoatings.com": "Joseph Chirichella",
    "marketing@passalacqua.com.br": "Passalacqua & Cia",
    "hello@ruglove.co.uk": "Rug Love Ltd",
    "info@floorsandwalls.ae": "Floors and Walls",
    "david@tristateepoxy.io": "Tri-State Epoxy",
    "rrusinski@swaydepoxy.com": "Roman Rusinski",
    "Scott@dbackpainting.com": "Diamondback Coatings",
    "shawnschierts@me.com": "Atomic Shield Coating",
    "diegobelato@hotmail.com": "Tecelagem Brasil",
    "n-botirxon@mail.ru": "Yekaterina Orexova",
    "chrisstone2010@hotmail.co.uk": "Cozy Flooring",
    "joni@thefloordesignstudio.co.uk": "Jonathan Reeves",
    "office@814epoxyandmore.com": "Joseph Fletcher",
    "contabilidad@unidekor.com.mx": "Unidekor",
    "hello@tilesman.com": "TilesMan",
    "joe@volf.com.au": "Volf Concrete Coatings",
    "jake@concretecote.com": "Jacob Vaughn / Concretecote.com",
    "rmullen@flooringsolutions.us": "Flooring Solutions",
    "info@cornerstonehsr.com": "Cornerstone",
    "jordi@terracassa.com": "terracassa.com",
    "info@battlebornpainting.com": "Battle Born Coatings",
    "erinm@iawlight.com": "IAW LIGHT",
    "onlinesales@alghomlas.co": "Musaed Abdul Latif Al Ghamlas",
    "mercadeo@listo.co": "TODACO S.A.S",
    "marketing@avanti-koberce.cz": "Avanti Koberce",
    "magdalenakinska@woodconnexions.com": "Wood Connexions Ltd",
}

# Monthly revenue projections per customer (May–Dec 2026)
# These are based on the Floori CSV and represent known renewal schedules.
# Status and amounts are overwritten by live Stripe data on each run.
MONTHLY_PROJECTIONS = {
    "The Trustee for THE NEJADIRAN FAMILY TRUST": [0,0,0,0,8457,0,0,0],
    "Carmel Floor": [0,600,0,0,0,0,0,0],
    "K Carrim Holdings Pty Ltd": [0,0,0,0,6500,0,0,0],
    "Heritage Carpets": [0,0,0,5391,0,0,0,0],
    "Garage Floor Coating": [0,0,0,5040,0,0,0,0],
    "Tapijten Demuynck": [5248,0,0,0,0,0,0,0],
    "Indusparquet": [0,0,0,0,0,3842,0,0],
    "VBL Import Pty Ltd": [0,0,0,0,0,3600,0,0],
    "Jason Larsen": [0,0,3499,0,0,0,0,0],
    "Bona US": [3225,3225,3225,3225,3225,3225,3225,3225],
    "Koreman Exclusive Carpets": [0,0,0,0,0,0,2988,0],
    "Supermat": [0,0,2500,0,0,0,0,0],
    "Fortress Floors of MN": [0,0,0,0,2300,0,0,0],
    "Angelo A Ayala Jr": [0,1800,0,0,0,0,0,0],
    "Robert Falls": [0,0,1800,0,0,0,0,0],
    "Tony Isgrove's Paint and Decorate": [0,0,0,1800,0,0,0,0],
    "Tough Floors Australia": [0,0,0,1800,0,0,0,0],
    "All Grind": [0,0,0,0,1800,0,0,0],
    "Jti Gulventreprise": [0,0,0,0,1800,0,0,0],
    "SHOUGUO JIAO": [0,0,0,0,1800,0,0,0],
    "Granicrete Australia": [0,0,0,0,1800,0,0,0],
    "603 Epoxy": [0,0,0,0,1800,0,0,0],
    "Chad Paulson": [0,1700,0,0,0,0,0,0],
    "Affordable Garage Carpet": [1650,0,0,0,0,0,0,0],
    "Rugs for Good Pty LTD": [1715,1715,1715,1715,1715,1715,1715,1715],
    "Tapetah": [1560,0,0,0,0,0,0,0],
    "Global Distribuição de Bens de Consumo": [295,295,295,295,295,295,295,295],
    "Cassandra Koprucu": [0,0,1440,0,0,0,0,0],
    "Randswood Flooring": [0,0,0,0,0,0,0,0],
    "SCI Coatings": [0,0,0,0,0,0,0,0],
    "The Carpet Company": [0,621,0,0,0,0,0,0],
    "NIAZI CHOHFI": [2500,0,0,0,0,0,0,0],
    "Koord Creativeloom": [774,0,0,0,0,0,0,0],
    "Camila Ordonez": [50,50,50,600,50,50,50,50],
    "Pravada": [599,599,599,599,599,599,599,599],
    "Alexander Marck": [499,499,499,499,499,499,499,499],
    "Acsento": [416,416,416,416,416,416,416,416],
    "Triff": [400,400,400,400,400,400,400,400],
    "Originate": [419,419,419,419,419,419,419,419],
    "Final Specs Flooring": [355,355,355,355,355,355,355,355],
    "ViaStar": [350,350,350,350,350,350,350,350],
    "Tenda dos Tapetes": [300,300,300,300,300,300,300,300],
    "Stauf USA": [299,299,299,299,299,299,299,299],
    "LA DISTRIBUIDORA DE CASIMIRES": [295,295,295,295,295,295,295,295],
    "Stile Società Cooperativa": [304,304,304,304,304,304,304,304],
    "MARBLELIFE": [249,249,249,249,249,249,249,249],
    "Sophie Lupien": [233,233,233,233,233,233,233,233],
    "TAJIMA ROOFING": [209,0,0,0,0,0,0,0],
    "Exclusive Rugs By Bijan": [207,207,207,207,207,207,207,207],
    "EDIFICOR S.R.L": [207,207,207,207,207,207,207,207],
    "Eva-last Hong Kong": [200,200,200,200,200,200,200,200],
    "Van Heugten Tapijtegels BV": [0,0,0,0,0,0,0,0],
    "Best Wool Carpets": [0,0,0,0,0,0,0,0],
    "The United Agencies": [0,0,0,5391,0,0,0,0],
    "Carolina Air Care": [0,0,0,0,0,0,1300,0],
    "Consorcio Persa": [0,0,0,0,0,0,0,0],
    "S W Gomes de Barros": [-116,116,116,116,116,116,116,116],
}


def stripe_status_to_label(status):
    return {
        "active": "Active",
        "past_due": "Past due",
        "unpaid": "Unpaid",
        "canceled": "Cancelled",
        "trialing": "Active",
        "incomplete": "Unpaid",
        "incomplete_expired": "Cancelled",
        "paused": "Cancelled",
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


def build_customer_map(subs):
    """Returns (by_email, by_name) — two indexes for the same customer data."""
    by_email = {}
    by_name  = {}  # normalized lowercase name → info

    for sub in subs:
        cust = sub.customer
        if isinstance(cust, str):
            email, name = "", ""
        else:
            email = getattr(cust, "email", None) or ""
            name  = getattr(cust, "name",  None) or ""

        if not name:
            name = EMAIL_TO_NAME.get(email, "") or EMAIL_TO_NAME.get(email.lower(), "")

        # subscription item details
        items_data = getattr(getattr(sub, "items", None), "data", []) or []
        item = items_data[0] if items_data else None

        amount   = 0
        interval = "Monthly"
        currency = "usd"

        if item:
            price = getattr(item, "price", None)
            if price:
                amount   = getattr(price, "unit_amount", 0) or 0
                currency = (getattr(price, "currency", "usd") or "usd").lower()
                recurring = getattr(price, "recurring", None)
                if recurring and getattr(recurring, "interval", None) == "year":
                    interval = "Annual"

        label = stripe_status_to_label(sub.status)

        # next invoice date — Stripe API 2024+: current_period_end lives in items.data[0]
        next_invoice_str = ""
        try:
            sub_dict = sub.to_dict()
            ts = None
            sd_items = sub_dict.get("items", {}).get("data", [])
            if sd_items:
                ts = sd_items[0].get("current_period_end")
            if not ts:
                ts = sub_dict.get("billing_cycle_anchor")
            if ts:
                next_invoice_str = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%b %d, %Y")
        except Exception:
            next_invoice_str = ""

        priority = {"Past due": 3, "Unpaid": 2, "Cancelled": 1, "Active": 0}
        info = {
            "name":         name or email,
            "email":        email,
            "status":       label,
            "interval":     interval,
            "amount":       amount,
            "currency":     currency,
            "next_invoice": next_invoice_str,
        }

        # index by email
        if email:
            if email in by_email:
                existing = by_email[email]
                if priority.get(label, 0) > priority.get(existing["status"], 0):
                    existing["status"] = label
                    existing["next_invoice"] = next_invoice_str
                existing["amount"] = max(existing["amount"], amount)
            else:
                by_email[email] = info

        # index by normalized name
        if name:
            nname = _normalize(name)
            if nname not in by_name:
                by_name[nname] = info
            else:
                existing = by_name[nname]
                if priority.get(label, 0) > priority.get(existing["status"], 0):
                    existing["status"] = label
                    existing["next_invoice"] = next_invoice_str
                existing["amount"] = max(existing["amount"], amount)

    return by_email, by_name


# Legal suffixes to strip before name comparison
_LEGAL_SUFFIXES = [
    " ltda", " ltda.", " s.a.", " s.a", " sa", " s/a", " inc", " inc.",
    " llc", " llc.", " ltd", " ltd.", " pty ltd", " pty", " gmbh",
    " s.r.l", " s.r.l.", " srl", " s.l.", " sl", " bv", " b.v.",
    " nv", " ag", " corp", " corp.", " co.", " co", " company",
    " group", " holdings", " cias", " cia", " & cia",
]

def _normalize(name: str) -> str:
    """Lowercase, strip legal suffixes and extra whitespace."""
    n = name.strip().lower()
    for sfx in _LEGAL_SUFFIXES:
        if n.endswith(sfx):
            n = n[: -len(sfx)].strip()
            break
    return n

def _fuzzy_match(csv_name: str, by_name: dict):
    """
    Try to find csv_name in by_name using progressively looser matching:
    1. Exact normalized match
    2. Stripe name starts with CSV name (or vice-versa), min 10 chars
    """
    csv_norm = _normalize(csv_name)

    # 1. exact after normalization
    if csv_norm in by_name:
        return by_name[csv_norm]

    # 2. prefix match — one starts with the other
    if len(csv_norm) >= 10:
        for stripe_norm, info in by_name.items():
            if stripe_norm.startswith(csv_norm) or csv_norm.startswith(stripe_norm):
                if len(stripe_norm) >= 10:
                    return info

    return None


def build_rows(customer_map):
    by_email, by_name = customer_map
    rows = []
    seen_names = set()

    # Pre-build: Stripe display name → CSV key (for projection lookup + dedup)
    stripe_to_csv = {}
    for csv_name in MONTHLY_PROJECTIONS:
        csv_norm = _normalize(csv_name)
        # exact normalized match
        if csv_norm in by_name:
            stripe_to_csv[by_name[csv_norm]["name"]] = csv_name
        else:
            # prefix match
            if len(csv_norm) >= 10:
                for stripe_norm, info in by_name.items():
                    if len(stripe_norm) >= 10:
                        if stripe_norm.startswith(csv_norm) or csv_norm.startswith(stripe_norm):
                            stripe_to_csv[info["name"]] = csv_name
                            break

    for email, info in by_email.items():
        stripe_name = info["name"]
        # Use CSV name if mapped, otherwise Stripe name
        display_name = stripe_to_csv.get(stripe_name, stripe_name)
        if not display_name or display_name in seen_names:
            continue
        seen_names.add(display_name)
        proj = MONTHLY_PROJECTIONS.get(display_name, [0,0,0,0,0,0,0,0])
        rows.append([
            display_name,
            info["status"],
            info["interval"],
            round(info["amount"] / 100) if info["currency"] == "usd" else 0,
            proj,
            info.get("next_invoice", ""),
        ])

    # CSV names not yet covered by email loop — fuzzy match or fallback
    for csv_name in MONTHLY_PROJECTIONS:
        if csv_name in seen_names:
            continue
        seen_names.add(csv_name)
        stripe_info = _fuzzy_match(csv_name, by_name)
        if stripe_info:
            rows.append([
                csv_name,
                stripe_info["status"],
                stripe_info["interval"],
                round(stripe_info["amount"] / 100) if stripe_info["currency"] == "usd" else 0,
                MONTHLY_PROJECTIONS[csv_name],
                stripe_info.get("next_invoice", ""),
            ])
        else:
            rows.append([csv_name, "Active", "Annual", 0, MONTHLY_PROJECTIONS[csv_name], ""])

    rows.sort(key=lambda r: r[3], reverse=True)

    # Final dedup: if two rows normalize to the same name, keep the one with higher base amount
    seen_norm = set()
    deduped = []
    for row in rows:
        norm = _normalize(row[0])
        if norm not in seen_norm:
            seen_norm.add(norm)
            deduped.append(row)

    return deduped


def compute_totals(rows):
    totals = [0.0] * 8
    active = [0.0] * 8
    problem = [0.0] * 8
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
    """Compute MRR and ARR breakdown from live Stripe subscription data."""
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
                annual_arr  += amount / 100
                annual_count += 1
            else:
                monthly_mrr += amount / 100
                monthly_count += 1
        except Exception:
            continue

    return {
        "monthly_mrr":    round(monthly_mrr, 2),
        "annual_arr":     round(annual_arr, 2),
        "annual_mrr":     round(annual_arr / 12, 2),
        "total_mrr":      round(monthly_mrr + annual_arr / 12, 2),
        "monthly_count":  monthly_count,
        "annual_count":   annual_count,
    }


def fetch_today_invoices(by_email, by_name):
    """Fetch invoices paid in the last 24h using Stripe Events API (filters by payment time, not creation time)."""
    import time
    since = int(time.time()) - 86400
    results = []
    try:
        params = {
            "type": "invoice.payment_succeeded",
            "limit": 100,
            "created": {"gte": since},
        }
        while True:
            page = stripe.Event.list(**params)
            for event in page.data:
                try:
                    inv_dict = event.to_dict().get("data", {}).get("object", {})
                    amount   = (inv_dict.get("amount_paid") or 0) / 100
                    currency = (inv_dict.get("currency") or "usd").upper()
                    created  = event.to_dict().get("created", 0)
                    time_str = datetime.fromtimestamp(int(created), tz=timezone.utc).strftime("%H:%M UTC") if created else ""

                    # resolve customer name
                    cust_id = inv_dict.get("customer", "")
                    cname   = inv_dict.get("customer_name") or ""
                    email   = inv_dict.get("customer_email") or ""
                    if not cname and email:
                        info  = by_email.get(email) or _fuzzy_match(email, by_name) or {}
                        cname = info.get("name", "") or EMAIL_TO_NAME.get(email, "")
                    if not cname:
                        cname = email or cust_id or "Unknown"

                    if amount > 0:
                        results.append({
                            "name":     cname,
                            "amount":   amount,
                            "currency": currency,
                            "time":     time_str,
                        })
                except Exception:
                    continue
            if not page.has_more:
                break
            params["starting_after"] = page.data[-1].id
    except Exception as e:
        print(f"  Warning: could not fetch today's invoices: {e}")

    results.sort(key=lambda x: x["time"], reverse=True)
    return results


def render_html(rows, totals, active_tot, problem_tot, synced, metrics, today_invoices):
    rows_js          = json.dumps(rows, ensure_ascii=False)
    totals_js        = json.dumps(totals)
    active_js        = json.dumps(active_tot)
    problem_js       = json.dumps(problem_tot)
    deductions_js    = json.dumps([-2616.45, 0, 0, 0, 0, 0, 0, 0])
    metrics_js       = json.dumps(metrics)
    today_js         = json.dumps(today_invoices, ensure_ascii=False)
    today_total      = sum(i["amount"] for i in today_invoices if i["currency"] == "USD")
    today_count      = len(today_invoices)
    today_total_fmt  = f"${today_total:,.0f}" if today_total else "$0"
    today_rows_html  = "".join(
        f'<tr style="border-bottom:0.5px solid var(--border2)">'
        f'<td style="padding:9px 12px;font-weight:500">{i["name"]}</td>'
        f'<td style="padding:9px 12px;text-align:right;font-variant-numeric:tabular-nums">'
        f'{i["currency"]} ${i["amount"]:,.2f}</td>'
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
  --green:#3B6D11;--green-bg:#EAF3DE;--green-bar:#7EC242;
  --red:#A32D2D;--red-bg:#FCEBEB;
  --amber:#854F0B;--amber-bg:#FAEEDA;
  --blue:#185FA5;--blue-bg:#E8F0FB;--blue-bar:#A8C4E0;
  --gray:#5F5E5A;--gray-bg:#F1EFE8;
  --stripe:#635BFF;
  --r:8px;--rl:12px;
  --font:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
}}
@media(prefers-color-scheme:dark){{
  :root{{
    --bg:#1c1c1a;--bg2:#242422;--bg3:#2c2c2a;
    --text:#e8e6df;--text2:#9e9d98;--text3:#6b6a65;
    --border:rgba(255,255,255,0.10);--border2:rgba(255,255,255,0.06);
    --green:#9FE1CB;--green-bg:#085041;--green-bar:#4D9A2A;
    --red:#F09595;--red-bg:#501313;
    --amber:#FAC775;--amber-bg:#412402;
    --blue:#7EB4E8;--blue-bg:#0D2A4A;--blue-bar:#2A5A8A;
    --gray:#B4B2A9;--gray-bg:#2C2C2A;
  }}
}}
body{{font-family:var(--font);background:var(--bg3);color:var(--text);font-size:14px;min-height:100vh}}
.wrap{{max-width:1120px;margin:0 auto;padding:1.5rem}}

/* topbar */
.topbar{{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.75rem;gap:1rem;flex-wrap:wrap}}
.topbar h1{{font-size:16px;font-weight:500;display:flex;align-items:center;gap:8px;color:var(--text)}}
.topbar h1 .si{{color:var(--stripe)}}
.synced{{font-size:11px;color:var(--text3);margin-top:3px}}
.mo-pill{{display:flex;align-items:center;gap:6px;background:var(--bg2);border:0.5px solid var(--border);border-radius:20px;padding:5px 14px;font-size:13px;font-weight:500}}
.mo-pill span{{min-width:72px;text-align:center}}

/* metric cards */
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:1.5rem}}
.mc{{background:var(--bg);border:0.5px solid var(--border2);border-radius:var(--rl);padding:1.1rem 1rem}}
.mc .lbl{{font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}}
.mc .val{{font-size:24px;font-weight:500;line-height:1.1}}
.mc .sub{{font-size:11px;color:var(--text3);margin-top:5px}}
.mc .trend{{font-size:11px;margin-top:4px}}

/* chart card */
.chart-card{{background:var(--bg);border:0.5px solid var(--border2);border-radius:var(--rl);padding:1.1rem 1.25rem;margin-bottom:1.5rem}}
.chart-card .ct{{font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.05em;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center}}
.chart-card .ct span{{font-size:12px;color:var(--text2);font-weight:400;text-transform:none;letter-spacing:0}}
.bar-chart{{display:flex;gap:6px;align-items:flex-end;height:120px}}
.bc-col{{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;transition:opacity .15s}}
.bc-col:hover{{opacity:.8}}
.bc-val{{font-size:9px;white-space:nowrap;color:var(--text3);transition:color .2s}}
.bc-val.sel{{color:var(--green);font-weight:600}}
.bc-val.sel-yr{{color:var(--blue);font-weight:600}}
.bc-bar{{width:100%;border-radius:3px 3px 0 0;transition:background .2s}}
.bc-lbl{{font-size:10px;color:var(--text3);transition:color .2s}}
.bc-lbl.sel{{color:var(--green);font-weight:500}}
.bc-lbl.sel-yr{{color:var(--blue);font-weight:500}}
.yr-divider{{width:1px;background:var(--border);margin:0 2px;align-self:stretch}}

/* 2-col */
.row2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:1.5rem}}
.card{{background:var(--bg);border:0.5px solid var(--border2);border-radius:var(--rl);padding:1.1rem 1.25rem}}
.card-title{{font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.05em;margin-bottom:14px}}

/* kv list inside card */
.kv{{display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:0.5px solid var(--border2);font-size:13px}}
.kv:last-child{{border-bottom:none}}
.kv .k{{color:var(--text2)}}
.kv .v{{font-weight:500}}
.kv .v.red{{color:var(--red)}}
.kv .v.green{{color:var(--green)}}
.kv .v.blue{{color:var(--blue)}}

/* invoices table */
.inv-table{{width:100%;border-collapse:collapse;font-size:13px}}
.inv-table th{{font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.04em;padding:7px 10px;background:var(--bg2);border-bottom:0.5px solid var(--border2);text-align:left;white-space:nowrap}}
.inv-table th.r,.inv-table td.r{{text-align:right}}
.inv-table td{{padding:8px 10px;border-bottom:0.5px solid var(--border2);vertical-align:middle}}
.inv-table tr:last-child td{{border-bottom:none}}
.inv-table tr:hover td{{background:var(--bg2)}}
.inv-wrap{{border-radius:var(--r);border:0.5px solid var(--border2);overflow:hidden}}
.empty{{text-align:center;color:var(--text3);font-size:13px;padding:2rem}}

/* customer table */
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
@media(max-width:700px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.row2{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="wrap">

  <div class="topbar">
    <div>
      <h1><span class="si">◈</span> Floori.io — Revenue Dashboard</h1>
      <p class="synced">Last synced: {synced} · Auto-updated weekdays at 9:30 AM BRT</p>
    </div>
    <div class="mo-pill">
      <span id="mo-label">Full Year 2026</span>
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
      <div class="sub">{today_count} payment{"s" if today_count != 1 else ""} in last 24h</div>
    </div>
  </div>

  <div class="chart-card">
    <div class="ct">
      <span>Monthly cashflow — click to select · Year shows all</span>
      <span id="chart-sub">Showing full year projection</span>
    </div>
    <div class="bar-chart" id="barchart"></div>
  </div>

  <div class="row2">
    <div class="card">
      <div class="card-title" id="sel-title">Selected period</div>
      <div class="kv"><span class="k">Expected revenue</span><span class="v green" id="sel-expected">—</span></div>
      <div class="kv"><span class="k">Active paying customers</span><span class="v" id="sel-active-count">—</span></div>
      <div class="kv"><span class="k">At risk (problem accounts)</span><span class="v red" id="sel-problem">—</span></div>
      <div class="kv"><span class="k">Lost to churn / cancelled</span><span class="v red" id="sel-churn">—</span></div>
    </div>
    <div class="card">
      <div class="card-title">Recent payments <span style="font-weight:400;font-size:10px;color:var(--text3);text-transform:none;letter-spacing:0">(last 24h)</span></div>
      {"<div class='inv-wrap'><table class='inv-table'><thead><tr><th>Customer</th><th class='r'>Amount</th><th>Time</th></tr></thead><tbody>" + today_rows_html + "</tbody></table></div>" if today_invoices else "<div class='empty'>No payments recorded in the last 24h</div>"}
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
    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th style="width:33%">Customer</th>
          <th style="width:13%">Status</th>
          <th style="width:16%">Next invoice</th>
          <th style="width:13%" class="r col-annual">Annual total</th>
          <th style="width:13%" class="r">Base amount</th>
          <th style="width:9%">Interval</th>
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
const MONTHS=["May 2026","Jun 2026","Jul 2026","Aug 2026","Sep 2026","Oct 2026","Nov 2026","Dec 2026"];
const MO_SHORT=["May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const D={rows_js}.filter(r=>r[1]!=="Cancelled");
const CANCELLED_D={rows_js}.filter(r=>r[1]==="Cancelled");
const BC={{"Active":"b-active","Past due":"b-pastdue","Unpaid":"b-unpaid"}};
const fmt=v=>v===0?"—":(v<0?"-":"")+new Intl.NumberFormat("en-US",{{style:"currency",currency:"USD",maximumFractionDigits:0}}).format(Math.abs(v));
const fmtS=v=>Math.abs(v)>=1000?(v<0?"-":"")+"$"+(Math.abs(v)/1000).toFixed(1)+"k":"$"+Math.round(v);

let mi=0,pg=1,sf="all"; // mi: 0-7=month, -1=year
const PS=15;

function byStatus(){{
  const f=sf;
  return D.filter(r=>f==="all"||( f==="Active"&&r[1]==="Active")||(f==="problem"&&(r[1]==="Past due"||r[1]==="Unpaid")));
}}

function setMonth(i){{
  mi=i;
  const isYr=mi===-1;
  document.getElementById("mo-label").textContent=isYr?"Full Year 2026":MONTHS[mi];
  document.getElementById("chart-sub").textContent=isYr?"Showing full year projection":"Showing "+MONTHS[mi];
  document.getElementById("sel-title").textContent=isYr?"Full Year 2026":MONTHS[mi];
  document.getElementById("tbl-title").textContent=isYr?"All customers":"Customers — "+MONTHS[mi];
  document.querySelectorAll(".col-annual").forEach(el=>el.style.display=isYr?"none":"");
  updateAll();
}}

function updateAll(){{
  sf=document.getElementById("flt").value;
  updateSelCard();
  renderChart();
  pg=1; _render();
}}

function updateSelCard(){{
  const all=D;
  const problems=all.filter(r=>r[1]==="Past due"||r[1]==="Unpaid");
  const cancelled=CANCELLED_D;
  let expected,activeCount,problemAmt,churnAmt;
  if(mi===-1){{
    expected=all.filter(r=>r[1]==="Active").reduce((s,r)=>s+r[4].reduce((a,v)=>a+v,0),0);
    activeCount=all.filter(r=>r[1]==="Active"&&r[4].some(v=>v>0)).length;
    problemAmt=problems.reduce((s,r)=>s+r[4].reduce((a,v)=>a+v,0),0);
    churnAmt=cancelled.reduce((s,r)=>s+r[4].reduce((a,v)=>a+v,0),0);
  }}else{{
    expected=all.filter(r=>r[1]==="Active").reduce((s,r)=>s+r[4][mi],0);
    activeCount=all.filter(r=>r[1]==="Active"&&r[4][mi]>0).length;
    problemAmt=problems.reduce((s,r)=>s+r[4][mi],0);
    churnAmt=cancelled.reduce((s,r)=>s+r[4][mi],0);
  }}
  document.getElementById("sel-expected").textContent=expected>0?fmt(expected):"—";
  document.getElementById("sel-active-count").textContent=activeCount+" customers";
  document.getElementById("sel-problem").textContent=problemAmt>0?"-"+fmtS(problemAmt):problems.length+" accounts";
  document.getElementById("sel-churn").textContent=churnAmt>0?"-"+fmtS(churnAmt):"$0";
}}

function renderChart(){{
  const base=byStatus();
  const mt=MONTHS.map((_,i)=>base.reduce((s,r)=>s+r[4][i],0));
  const yt=mt.reduce((a,v)=>a+v,0);
  const mx=Math.max(...mt,yt)||1;
  let html="";
  mt.forEach((v,i)=>{{
    const sel=mi===i,h=Math.max(4,Math.round((v/mx)*100));
    const bg=sel?"var(--green-bar)":"var(--bg2)";
    html+=`<div class="bc-col" onclick="setMonth(${{i}})">
      <span class="bc-val${{sel?" sel":""}}">${{v>0?fmtS(v):"—"}}</span>
      <div class="bc-bar" style="height:${{h}}px;background:${{bg}}"></div>
      <span class="bc-lbl${{sel?" sel":""}}">${{MO_SHORT[i]}}</span>
    </div>`;
  }});
  const selYr=mi===-1,hYr=Math.max(4,Math.round((yt/mx)*100));
  html+=`<div class="yr-divider"></div>
  <div class="bc-col" onclick="setMonth(-1)">
    <span class="bc-val${{selYr?" sel-yr":""}}">${{fmtS(yt)}}</span>
    <div class="bc-bar" style="height:${{hYr}}px;background:${{selYr?"var(--blue)":"var(--blue-bar)"}};border-radius:3px 3px 0 0"></div>
    <span class="bc-lbl${{selYr?" sel-yr":""}}">Year</span>
  </div>`;
  document.getElementById("barchart").innerHTML=html;
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
    return `<tr>
      <td style="font-weight:500">${{r[0]}}</td>
      <td><span class="badge ${{BC[r[1]]||"b-unpaid"}}">${{r[1]}}</span></td>
      <td style="font-size:12px;color:${{prob?"var(--red)":"var(--text2)"}};font-weight:${{prob?500:400}}">${{r[5]||"—"}}</td>
      <td class="r col-annual" style="color:var(--text2)">${{annualTotal>0?fmt(annualTotal):"—"}}</td>
      <td class="r" style="color:var(--text2)">$${{r[3].toLocaleString()}}</td>
      <td><span class="freq">${{r[2]}}</span></td>
    </tr>`;
  }}).join("");
}}

setMonth(-1);
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("Fetching subscriptions from Stripe...")
    subs = fetch_all_subscriptions()
    print(f"  {len(subs)} subscriptions fetched")

    customer_map = build_customer_map(subs)
    dated = sum(1 for v in customer_map[0].values() if v.get("next_invoice"))
    print(f"  {dated}/{len(customer_map[0])} customers have a next invoice date")

    print("Computing subscription metrics...")
    metrics = compute_subscription_metrics(subs)
    print(f"  MRR: ${metrics['total_mrr']:,.0f} (monthly ${metrics['monthly_mrr']:,.0f} + annual equiv. ${metrics['annual_mrr']:,.0f})")

    print("Fetching today's invoices...")
    today_invoices = fetch_today_invoices(customer_map[0], customer_map[1])
    print(f"  {len(today_invoices)} invoice(s) paid in last 24h")

    rows = build_rows(customer_map)
    totals, active_tot, problem_tot = compute_totals(rows)

    synced = datetime.now(timezone.utc).strftime("%b %d, %Y at %H:%M UTC")
    html = render_html(rows, totals, active_tot, problem_tot, synced, metrics, today_invoices)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  index.html written — {len(rows)} customers, synced {synced}")
