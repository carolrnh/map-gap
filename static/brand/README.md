# Shop vs Shop: final logo kit

Wordmark: "fight card" (SHOP / VS / SHOP). Icon: split map pin.
Colors: dark #1F2A24 · cream #EFE6D4 · orange #BE5925.
Fonts: Anton (wordmark), Barlow Condensed Bold (tagline), Barlow Condensed SemiBold (URL on the share image). All are free Google Fonts, and every SVG has its text turned into outlines, so no fonts need to be installed.

## Main lockup with tagline ("MAPS CHECKUP · HVAC & PLUMBING"): hero, decks, print
- shopvsshop-lockup-tagline-on-cream.svg / .png: on a cream background
- shopvsshop-lockup-tagline-on-dark.svg / .png: on a dark #1F2A24 background
- shopvsshop-lockup-tagline-transparent-for-cream-bg.svg / .png: transparent, dark ink, for light backgrounds
- shopvsshop-lockup-tagline-transparent-for-dark-bg.svg / .png: transparent, cream ink, for dark backgrounds
(The PNGs are 1600 px wide.)

## Header lockup (no tagline): site header bar
- shopvsshop-header-transparent-for-dark-bg.svg: use this on the current dark header (#1F2A24)
- shopvsshop-header-transparent-for-dark-bg@1x.png / @2x.png: 170×40 / 340×80
- shopvsshop-header-transparent-for-cream-bg.svg (+ @1x/@2x PNG): for a light header
- shopvsshop-header-on-dark.svg / shopvsshop-header-on-cream.svg: same art with a solid background
Tested in a 98 px header at 40 px tall. Suggested CSS: `height:40px; width:auto`.

## Icon / favicon (split pin)
- favicon.ico: 16, 32 and 48 px, for browser tabs (`<link rel="icon" href="/favicon.ico" sizes="any">`)
- favicon.svg: vector favicon with a stronger edge so it stays visible on dark tabs (`<link rel="icon" type="image/svg+xml" href="/favicon.svg">`)
- favicon-16.png, favicon-32.png, favicon-48.png: PNG favicons
- apple-touch-icon.png: 180×180, full-bleed square (iOS rounds the corners), `<link rel="apple-touch-icon" href="/apple-touch-icon.png">`
- icon-192.png, icon-512.png: web app manifest / PWA icons
- icon.svg: master icon, a rounded dark tile with a subtle lighter edge
- pin-transparent-for-dark-bg.svg (+ -512.png): cream/orange pin with no tile, for dark backgrounds
- pin-transparent-for-cream-bg.svg (+ -512.png): dark/orange pin with no tile, for light backgrounds

## Social
- og-image-1200x630.png (+ .svg): Open Graph / X / LinkedIn share image (`<meta property="og:image" ...>`, `twitter:card=summary_large_image`)

## Board
- board-final.png: overview of everything above, including a real-size header mock and browser-tab mock
