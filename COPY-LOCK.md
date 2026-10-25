# Copy lock — updated 2026-09-29 (Carol approved the site-audit recheck)

Locked homepage strings (do not regress):

- **Title / H1:** Why isn’t my HVAC or plumbing shop showing up on Google Maps?
- **Header line:** Google Maps checkup for HVAC & plumbing shops
- **Lede:** Paste your Google listing. In under a minute you’ll see 3 things the shops above you have that you don’t. Free, no login.
- **Button:** Show my 3 free gaps
- **Suspension (below the card, not under the button, and not the first price):** If Google *suspended* the listing, this check will not get it back. That’s an appeal to Google.
- **Prices:** Free check / Competitor report — $195 / listing rebuild $397. No $397/mo on this site. Do not call the paid tier “full check” (it reads like “free check”).
- **Timing:** Homepage lede is “In under a minute you’ll see…”. The loading note says “usually under a minute.” The expired page says “This check expired” once, then “Run it again (free, usually under a minute).”
- **Trust line (once, in the footer):** You keep the listing. No ranking is guaranteed. Do not repeat that sentence on subpages.
- **Wording:** checkup, not audit.
- **Refund (approved, once on the homepage, in pricing):** If the report doesn’t show at least 3 specific fixes for your listing, I’ll refund you. No chat and no phone.
- **Other MapGap products** (mapgap.app, mapgap.pages.dev) stay on `/what-is-shop-vs-shop` only. The product name is Shop vs Shop, at shopvsshop.com. Support email: support@shopvsshop.com.

**Stripe:** `report.PRICE` is the label ($195). The card amount is the Stripe Payment Link, not a number in this repo.

**Saved checks:** the public result is signed into the `/teaser/` link so a Render free-tier redeploy does not 404 it. The server sqlite copy does not survive a redeploy.

**Do not:**

- Add testimonials, a named operator, or a sample report image. A TODO marks where a sample report would go.
- Add a chat or phone path.
- Put “Not mapgaps.com” or the other-MapGap line back in the header.
- Change the $195 or $397 prices.
