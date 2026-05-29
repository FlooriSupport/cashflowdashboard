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
    """Returns {email: {name, status, interval, amount, currency}}"""
    result = {}
    for sub in subs:
        # customer may be an expanded object or just a string ID
        cust = sub.customer
        if isinstance(cust, str):
            email, name = "", ""
        else:
            email = getattr(cust, "email", None) or ""
            name  = getattr(cust, "name",  None) or ""

        if not name:
            name = EMAIL_TO_NAME.get(email, "") or EMAIL_TO_NAME.get(email.lower(), "")

        # pick the first subscription item
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

        # consolidate multiple subs per email — keep most severe status
        priority = {"Past due": 3, "Unpaid": 2, "Cancelled": 1, "Active": 0}
        if email in result:
            existing = result[email]
            if priority.get(label, 0) > priority.get(existing["status"], 0):
                existing["status"] = label
            existing["amount"] = max(existing["amount"], amount)
        else:
            result[email] = {
                "name":     name or email,
                "email":    email,
                "status":   label,
                "interval": interval,
                "amount":   amount,
                "currency": currency,
            }
    return result


def build_rows(customer_map):
    rows = []
    seen_names = set()

    for email, info in customer_map.items():
        name = info["name"]
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        proj = MONTHLY_PROJECTIONS.get(name, [0,0,0,0,0,0,0,0])
        rows.append([
            name,
            info["status"],
            info["interval"],
            round(info["amount"] / 100) if info["currency"] == "usd" else 0,
            proj,
        ])

    # add any CSV names not found in Stripe (keep their last known status)
    for csv_name in MONTHLY_PROJECTIONS:
        if csv_name not in seen_names:
            rows.append([csv_name, "Active", "Annual", 0, MONTHLY_PROJECTIONS[csv_name]])

    rows.sort(key=lambda r: r[3], reverse=True)
    return rows


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


def render_html(rows, totals, active_tot, problem_tot, synced):
    rows_js = json.dumps(rows, ensure_ascii=False)
    totals_js = json.dumps(totals)
    active_js = json.dumps(active_tot)
    problem_js = json.dumps(problem_tot)
    deductions_js = json.dumps([-2616.45, 0, 0, 0, 0, 0, 0, 0])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Floori.io — Stripe Revenue Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  :root{{
    --bg:#ffffff;--bg2:#f5f5f3;--bg3:#eeece6;
    --text:#1a1a18;--text2:#6b6a65;--text3:#9e9d98;
    --border:rgba(0,0,0,0.12);--border2:rgba(0,0,0,0.08);
    --green:#3B6D11;--green-bg:#EAF3DE;
    --red:#A32D2D;--red-bg:#FCEBEB;
    --amber:#854F0B;--amber-bg:#FAEEDA;
    --gray:#5F5E5A;--gray-bg:#F1EFE8;
    --stripe:#635BFF;
    --radius:8px;--radius-lg:12px;
    --font:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  }}
  @media(prefers-color-scheme:dark){{
    :root{{
      --bg:#1c1c1a;--bg2:#242422;--bg3:#2c2c2a;
      --text:#e8e6df;--text2:#9e9d98;--text3:#6b6a65;
      --border:rgba(255,255,255,0.12);--border2:rgba(255,255,255,0.07);
      --green:#9FE1CB;--green-bg:#085041;
      --red:#F09595;--red-bg:#501313;
      --amber:#FAC775;--amber-bg:#412402;
      --gray:#B4B2A9;--gray-bg:#2C2C2A;
    }}
  }}
  body{{font-family:var(--font);background:var(--bg3);color:var(--text);font-size:14px;min-height:100vh}}
  .container{{max-width:1100px;margin:0 auto;padding:1.5rem}}
  .topbar{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1.5rem;gap:1rem;flex-wrap:wrap}}
  .topbar h1{{font-size:17px;font-weight:500;display:flex;align-items:center;gap:8px}}
  .topbar h1 .si{{color:var(--stripe)}}
  .topbar p{{font-size:12px;color:var(--text2);margin-top:3px}}
  .top-right{{display:flex;align-items:center;gap:10px}}
  .month-nav{{display:flex;align-items:center;gap:6px}}
  .month-nav button,.btn{{background:var(--bg);border:0.5px solid var(--border);border-radius:var(--radius);padding:6px 10px;cursor:pointer;color:var(--text);font-size:13px;transition:background .15s}}
  .btn{{padding:6px 14px;display:inline-flex;align-items:center;gap:6px}}
  .month-nav button:hover,.btn:hover{{background:var(--bg2)}}
  .month-nav button:disabled{{opacity:.35;cursor:default}}
  .month-label{{font-size:14px;font-weight:500;min-width:88px;text-align:center}}
  .synced{{font-size:11px;color:var(--text3)}}
  .metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:1.5rem}}
  .mc{{background:var(--bg2);border-radius:var(--radius);padding:1rem}}
  .mc .lbl{{font-size:12px;color:var(--text2);margin-bottom:4px}}
  .mc .val{{font-size:22px;font-weight:500}}
  .mc .sub{{font-size:12px;color:var(--text2);margin-top:2px}}
  .row2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:1.5rem}}
  .card{{background:var(--bg);border:0.5px solid var(--border2);border-radius:var(--radius-lg);padding:1rem 1.25rem}}
  .card-title{{font-size:11px;font-weight:500;color:var(--text2);text-transform:uppercase;letter-spacing:.05em;margin-bottom:14px}}
  .bar-row{{margin-bottom:12px}}
  .bar-meta{{display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px}}
  .bar-meta span:first-child{{color:var(--text2)}}
  .pct{{color:var(--text3);font-weight:400}}
  .bar-track{{height:8px;background:var(--bg2);border-radius:4px;overflow:hidden}}
  .bar-fill{{height:100%;border-radius:4px;transition:width .4s ease}}
  .sparkwrap{{display:flex;gap:4px;align-items:flex-end;height:90px;margin-bottom:6px}}
  .spark-bar{{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer}}
  .spark-fill{{width:100%;border-radius:3px 3px 0 0;transition:background .2s}}
  .spark-lbl{{font-size:10px;color:var(--text2)}}
  .spark-lbl.active{{color:var(--green);font-weight:500}}
  .spark-minmax{{display:flex;justify-content:space-between;font-size:11px;color:var(--text3)}}
  .tbl-section{{background:var(--bg);border:0.5px solid var(--border2);border-radius:var(--radius-lg);padding:1rem 1.25rem}}
  .tbl-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:8px;flex-wrap:wrap}}
  .tbl-controls{{display:flex;gap:8px;align-items:center}}
  .tbl-controls input,.tbl-controls select{{background:var(--bg);border:0.5px solid var(--border);border-radius:var(--radius);padding:5px 9px;font-size:13px;color:var(--text)}}
  .tbl-controls input{{width:160px}}
  .tbl-wrap{{overflow-x:auto;border-radius:var(--radius);border:0.5px solid var(--border2)}}
  table{{width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed}}
  thead th{{font-size:11px;font-weight:500;color:var(--text2);text-transform:uppercase;letter-spacing:.04em;padding:8px 12px;background:var(--bg2);border-bottom:0.5px solid var(--border2);text-align:left;white-space:nowrap}}
  th.r,td.r{{text-align:right}}
  tbody tr{{border-bottom:0.5px solid var(--border2);transition:background .1s}}
  tbody tr:last-child{{border-bottom:none}}
  tbody tr:hover{{background:var(--bg2)}}
  tbody td{{padding:9px 12px;vertical-align:middle;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
  .badge{{display:inline-flex;font-size:11px;padding:2px 8px;border-radius:20px;font-weight:500}}
  .b-active{{background:var(--green-bg);color:var(--green)}}
  .b-pastdue{{background:var(--red-bg);color:var(--red)}}
  .b-unpaid{{background:var(--amber-bg);color:var(--amber)}}
  .b-cancelled{{background:var(--gray-bg);color:var(--gray)}}
  .freq{{font-size:11px;background:var(--bg2);padding:1px 6px;border-radius:20px;color:var(--text2)}}
  .amt-pos{{font-weight:500;font-variant-numeric:tabular-nums}}
  .amt-neg{{font-weight:500;color:var(--red);font-variant-numeric:tabular-nums}}
  .amt-zero{{color:var(--text3)}}
  .pagination{{display:flex;align-items:center;gap:8px;margin-top:12px;font-size:13px;color:var(--text2)}}
  .pagination button{{background:var(--bg);border:0.5px solid var(--border2);border-radius:var(--radius);padding:4px 10px;cursor:pointer;color:var(--text);font-size:12px}}
  .pagination button:disabled{{opacity:.35;cursor:default}}
  .pagination button:not(:disabled):hover{{background:var(--bg2)}}
  #ct-lbl{{margin-left:auto;font-size:12px}}
  @media(max-width:700px){{
    .metrics{{grid-template-columns:repeat(2,1fr)}}
    .row2{{grid-template-columns:1fr}}
  }}
</style>
</head>
<body>
<div class="container">
  <div class="topbar">
    <div>
      <h1><span class="si">◈</span> Floori.io — Stripe Revenue Dashboard</h1>
      <p class="synced">Last synced: {synced} &nbsp;·&nbsp; Auto-updated weekdays at 9:30 AM BRT</p>
    </div>
    <div class="top-right">
      <div class="month-nav">
        <button id="prev-mo" onclick="setMonth(mi-1)" disabled>&#8249;</button>
        <span class="month-label" id="mo-label">May 2026</span>
        <button id="next-mo" onclick="setMonth(mi+1)">&#8250;</button>
      </div>
    </div>
  </div>

  <div class="metrics">
    <div class="mc"><div class="lbl">Expected result</div><div class="val" id="m-expected" style="color:var(--green)">—</div><div class="sub">this month</div></div>
    <div class="mc"><div class="lbl">Active paying</div><div class="val" id="m-active">—</div><div class="sub" id="m-active-sub">—</div></div>
    <div class="mc"><div class="lbl">Problem accounts</div><div class="val" id="m-problem" style="color:var(--red)">—</div><div class="sub">past due / unpaid</div></div>
    <div class="mc"><div class="lbl">Deductions</div><div class="val" id="m-deductions" style="color:var(--gray)">—</div><div class="sub">cancellations</div></div>
  </div>

  <div class="row2">
    <div class="card">
      <div class="card-title">Monthly overview — click to navigate</div>
      <div class="sparkwrap" id="sparkbars"></div>
      <div class="spark-minmax"><span id="sp-min"></span><span id="sp-max"></span></div>
    </div>
    <div class="card">
      <div class="card-title">Status breakdown</div>
      <div id="status-bars"></div>
    </div>
  </div>

  <div class="tbl-section">
    <div class="tbl-header">
      <div class="card-title" id="tbl-title" style="margin-bottom:0">Customers — May 2026</div>
      <div class="tbl-controls">
        <input id="search" placeholder="Search customer…" oninput="renderTable()">
        <select id="flt" onchange="renderTable()">
          <option value="all">All</option>
          <option value="has-revenue">Has revenue</option>
          <option value="no-revenue">No revenue this month</option>
          <option value="problem">Problem accounts</option>
          <option value="Active">Active</option>
          <option value="Past due">Past due</option>
          <option value="Unpaid">Unpaid</option>
          <option value="Cancelled">Canceled</option>
        </select>
      </div>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th style="width:32%">Customer</th>
          <th style="width:13%">Status</th>
          <th style="width:13%" class="r" id="col-month">May 2026</th>
          <th style="width:13%" class="r">Base amount</th>
          <th style="width:10%">Interval</th>
        </tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
    <div class="pagination">
      <button id="prev-pg" onclick="go(-1)" disabled>&#8592; Prev</button>
      <span id="pg-info">Page 1 of 1</span>
      <button id="next-pg" onclick="go(1)">Next &#8594;</button>
      <span id="ct-lbl"></span>
    </div>
  </div>
</div>

<script>
const MONTHS=["May 2026","Jun 2026","Jul 2026","Aug 2026","Sep 2026","Oct 2026","Nov 2026","Dec 2026"];
const TOTALS={totals_js};
const ACTIVE_TOT={active_js};
const PROBLEM_TOT={problem_js};
const DEDUCTIONS={deductions_js};
const D={rows_js};
const BC={{"Active":"b-active","Past due":"b-pastdue","Unpaid":"b-unpaid","Cancelled":"b-cancelled"}};
const fmt=v=>v===0?"—":(v<0?"-":"")+new Intl.NumberFormat("en-US",{{style:"currency",currency:"USD",maximumFractionDigits:0}}).format(Math.abs(v));
const fmtShort=v=>Math.abs(v)>=1000?(v<0?"-":"")+"$"+(Math.abs(v)/1000).toFixed(1)+"k":"$"+Math.round(v);
let mi=0,pg=1;const PS=15;
function setMonth(i){{
  mi=Math.max(0,Math.min(7,i));
  document.getElementById("prev-mo").disabled=mi===0;
  document.getElementById("next-mo").disabled=mi===7;
  document.getElementById("mo-label").textContent=MONTHS[mi];
  document.getElementById("col-month").textContent=MONTHS[mi];
  document.getElementById("tbl-title").textContent="Customers — "+MONTHS[mi];
  updateMetrics();updateSpark();pg=1;renderTable();
}}
function updateMetrics(){{
  document.getElementById("m-expected").textContent=fmtShort(TOTALS[mi]);
  const ac=D.filter(r=>r[4][mi]>0&&r[1]==="Active").length;
  document.getElementById("m-active").textContent=fmtShort(ACTIVE_TOT[mi]);
  document.getElementById("m-active-sub").textContent=ac+" customers with revenue";
  document.getElementById("m-problem").textContent=fmtShort(PROBLEM_TOT[mi]);
  const d=DEDUCTIONS[mi];
  document.getElementById("m-deductions").textContent=d<0?"-"+fmtShort(Math.abs(d)):"$0";
}}
function updateSpark(){{
  const max=Math.max(...TOTALS),min=Math.min(...TOTALS);
  document.getElementById("sp-min").textContent=fmtShort(min);
  document.getElementById("sp-max").textContent=fmtShort(max);
  const labels=["May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  document.getElementById("sparkbars").innerHTML=TOTALS.map((v,i)=>{{
    const h=Math.round((v/max)*82),active=i===mi;
    return `<div class="spark-bar" onclick="setMonth(${{i}})"><div class="spark-fill" style="height:${{h}}px;background:${{active?"#3B6D11":"#C0DD97"}}"></div><span class="spark-lbl${{active?" active":""}}">${{labels[i]}}</span></div>`;
  }}).join("");
  const total=D.length||1;
  const sb=[
    {{label:"Active",count:D.filter(r=>r[1]==="Active").length,color:"#639922"}},
    {{label:"Past due",count:D.filter(r=>r[1]==="Past due").length,color:"#E24B4A"}},
    {{label:"Unpaid",count:D.filter(r=>r[1]==="Unpaid").length,color:"#BA7517"}},
    {{label:"Cancelled",count:D.filter(r=>r[1]==="Cancelled").length,color:"#888780"}},
  ];
  document.getElementById("status-bars").innerHTML=sb.map(b=>`<div class="bar-row"><div class="bar-meta"><span>${{b.label}}</span><span>${{b.count}} <span class="pct">(${{Math.round(b.count/total*100)}}%)</span></span></div><div class="bar-track"><div class="bar-fill" style="width:${{Math.round(b.count/total*100)}}%;background:${{b.color}}"></div></div></div>`).join("");
}}
function getFiltered(){{
  const q=document.getElementById("search").value.toLowerCase();
  const f=document.getElementById("flt").value;
  return D.filter(r=>{{
    const v=r[4][mi];
    const mf=f==="all"||(f==="has-revenue"&&v>0)||(f==="no-revenue"&&v===0)||(f==="problem"&&(r[1]==="Past due"||r[1]==="Unpaid"))||r[1]===f;
    return mf&&(!q||r[0].toLowerCase().includes(q));
  }});
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
    const v=r[4][mi],ac=v>0?"amt-pos":v<0?"amt-neg":"amt-zero";
    return `<tr style="${{i===rows.length-1?"border-bottom:none":""}}"><td style="font-weight:500">${{r[0]}}</td><td><span class="badge ${{BC[r[1]]||"b-cancelled"}}">${{r[1]}}</span></td><td class="r ${{ac}}">${{fmt(v)}}</td><td class="r" style="color:var(--text2)">$${{r[3].toLocaleString()}}</td><td><span class="freq">${{r[2]}}</span></td></tr>`;
  }}).join("");
}}
setMonth(0);
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("Fetching subscriptions from Stripe...")
    subs = fetch_all_subscriptions()
    print(f"  {len(subs)} subscriptions fetched")

    customer_map = build_customer_map(subs)
    rows = build_rows(customer_map)
    totals, active_tot, problem_tot = compute_totals(rows)

    synced = datetime.now(timezone.utc).strftime("%b %d, %Y at %H:%M UTC")
    html = render_html(rows, totals, active_tot, problem_tot, synced)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  index.html written — {len(rows)} customers, synced {synced}")
