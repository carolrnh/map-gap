# Copy lock — Offer pack v1b + CoS 2026-08-26 3:38pm ET

**Source of truth:** `/workspace/offer-gbp-v1.md`

Locked homepage strings (do not regress):
- **Title / H1:** Why isn’t my business showing up on Google Maps?
- **Who-filter (not the H1):** For HVAC and plumbing shops only.
- **Button:** Show me why I’m not showing
- **Suspension (under the form, not a CTA):** If Google *suspended* the listing, this report will not get it back. That’s an appeal to Google. Don’t pay $197 for that.
- **SKUs:** T free teaser / A $197 / B $397 thank-you only. No $397/mo on this site.

**App:** Flask via `./run.sh` on 127.0.0.1:8787. Template for `/` is `templates/landing.html`.

**Do not:**
- Overwrite `lookup.py` / `generate.mjs` with a static H1 page
- Put HVAC/plumbing in the H1
- Turn checkout on until Raven confirms Stripe is theirs
- Ping Raven about Stripe

`generate.mjs` writes `reports/*.json` only.
