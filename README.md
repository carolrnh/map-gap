# Map Gap

Self-serve Google Maps checkup for US HVAC and plumbing owners.

Flow: landing → business name + city **or** Google listing URL → free check (3 things the shops above you have) → **$195** competitor report. After pay, thank-you may offer **$397 Listing Rebuild**. There is **no monthly plan** on this site.

The $195 figure is the label in `report.PRICE`. The amount Stripe charges is set on the Payment Link in Stripe, not in this repo.

Copy: offer pack v1b (`/workspace/offer-gbp-v1.md`). Raven does not walk or sell. No spam or mailing list; at most one personal outreach email, sent by hand, and we stop on request. No ranking guarantee. Public data only — review counts are never invented.

This folder is the only site. Do not use `/workspace/mappack`.

## How to run

```bash
cd /workspace/map-gap
./run.sh
```

Open **http://127.0.0.1:8787**

Legal: **http://127.0.0.1:8787/legal**

First run creates `.venv` and installs Flask (`requirements.txt`). No paid APIs. Spend $0.

Manual:

```bash
cd /workspace/map-gap
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

`MAPGAP_PORT` defaults to `8787`. `MAPGAP_HOST` defaults to `0.0.0.0`.

## Stripe (optional)

Do not fake charges. If `STRIPE_PAYMENT_LINK_URL` is unset, the $195 button reads **Payment not connected yet**. Update the Payment Link in Stripe if it still charges $197.

```bash
cp .env.example .env
# or export:
export STRIPE_PAYMENT_LINK_URL='https://buy.stripe.com/...'
export STRIPE_REBUILD_PAYMENT_LINK_URL='https://buy.stripe.com/...'   # $397 thank-you only
./run.sh
```

In Stripe, set the Payment Link after-payment URL to `http://127.0.0.1:8787/thanks?report=<id>` (or your public origin). v1 delivers on that page — the app sends no email (Stripe sends the receipt).

## Pages

| Path | What |
|---|---|
| `/` | Landing + lookup |
| `/what-is-map-gap` | Name-ownership: this Map Gap vs mapgaps.com / MAPGAPS protein |
| `POST /lookup` → `/teaser/<signed link>` | Free check. The link holds the public result so it still opens after a redeploy. |
| `/pay/<id>` | $195 checkout stub |
| `/thanks` | Post-pay drop + $397 Listing Rebuild |
| `/legal` | Legal / hard nos |

If public data is thin, the check still lists what we could and could not fetch. Review counts stay UNKNOWN. The $195 button stays hidden on a thin result, and reads **Payment not connected yet** until a Stripe Payment Link is set. It does not fake a charge.

## Data

Saved checks are signed into the result URL (`result_link.py`). Render’s free tier wipes the disk on deploy, so a sqlite id alone 404s. The server still keeps a sqlite copy until the next deploy. A missing or old link shows “This check expired” and “Run it again (free, usually under a minute).” Payment unlock is not stored in the link.

- Default: OpenStreetMap Nominatim (1 request/second), plus the public page when a Google URL is pasted.
- 90-day review velocity and Google posts stay **UNKNOWN** unless they were on that page. UNKNOWN is not zero.
- HVAC/plumbing only. US only.

### Google Places (off until Carol sets it)

`USE_GOOGLE_PLACES` defaults off. With the flag off, or with no `GOOGLE_PLACES_API_KEY`, the Nominatim path above is unchanged.

To turn Places on, set both:

- `USE_GOOGLE_PLACES=true`
- `GOOGLE_PLACES_API_KEY` (server-side only)

`PLACES_DAILY_CAP` defaults to 30 Places HTTP calls per UTC day. One check is an IDs-only Text Search, one Place Details call for the business, and a Text Search for competitors restricted to a radius around the shop (`includePureServiceAreaBusinesses`). The first search is 25 km. If fewer than 3 same-trade shops are inside it, the radius widens to 50 km, then 100 km, then 160 km. Each widen is another Text Search. Competitor details are not fetched one by one. Photos are shown as 0–9 or 10+. Google Posts and 90-day review velocity are not reported. Place IDs are what we store; opening the result loads Places again and counts against the cap.

`PLACES_IP_LIMIT` defaults to 5 lookup-form checks per `PLACES_IP_WINDOW_SECONDS` (default 3600). Over the limit, the form returns HTTP 429 with "Too many checks from this connection. Please wait and try again." That counter is separate from the daily Places cap.

## Honesty

- Never invent review counts, ratings, competitors, or Google rankings.
- No “#1 on Google.” You keep the listing.
- No Alventra / Forge / 14-years claims.
