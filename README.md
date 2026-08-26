# Map Gap

Self-serve **Map Pack Report** for US HVAC and plumbing owners.

Flow: landing → business name + city **or** Google listing URL → free teaser (3 public bullets) → **$197** paywall. After pay, thank-you may offer **$397 Listing Rebuild**. There is **no monthly plan** on this site.

Copy: offer pack v1b (`/workspace/offer-gbp-v1.md`). Raven does not walk or sell. No email. No DMs. No ranking guarantee. Public data only — review counts are never invented.

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

Do not fake charges. If `STRIPE_PAYMENT_LINK_URL` is unset, the $197 button reads **Payment not connected yet**.

```bash
cp .env.example .env
# or export:
export STRIPE_PAYMENT_LINK_URL='https://buy.stripe.com/...'
export STRIPE_REBUILD_PAYMENT_LINK_URL='https://buy.stripe.com/...'   # $397 thank-you only
./run.sh
```

In Stripe, set the Payment Link after-payment URL to `http://127.0.0.1:8787/thanks?report=<id>` (or your public origin). v1 delivers on that page — no email.

## Pages

| Path | What |
|---|---|
| `/` | Landing + lookup |
| `POST /lookup` → `/r/<id>` | Free teaser (NAP, source log, UNKNOWN reviews) + $197 paywall |
| `/pay/<id>` | $197 checkout stub |
| `/thanks` | Post-pay drop + $397 Listing Rebuild |
| `/legal` | Legal / hard nos |

If public data is thin, the teaser still lists what we could and could not fetch. Review counts stay UNKNOWN. The $197 button still appears; it is disabled with **Payment not connected yet** until a Stripe Payment Link is set. It does not fake a charge.

## Data

- Identity + nearby shops: OpenStreetMap Nominatim (1 request/second).
- If the buyer pastes a Google Maps / GBP URL, that public page is fetched once. JSON-LD only.
- 90-day review velocity and Google posts stay **UNKNOWN** unless they were on the page. UNKNOWN is not zero.
- HVAC/plumbing only. US only.

## Honesty

- Never invent review counts, ratings, competitors, or map-pack positions.
- No “#1 on Google.” You keep the listing.
- No Alventra / Forge / 14-years claims.
