#!/usr/bin/env node
/**
 * Map Gap — SKU A generator (local prototype)
 * Public GBP page only. If fetch is blocked or a field is not visible, write UNKNOWN.
 * Never invent review counts, stars, categories, competitors, or positions.
 * Writes reports/<slug>.json ONLY. Never write index.html or templates/*.html.
 * Homepage copy is locked in COPY-LOCK.md / offer-gbp-v1.md.
 *
 * Usage:
 *   node generate.mjs --url "https://maps.google.com/..." --email you@example.com
 *   node generate.mjs --name "Shop Name" --city "Columbus" --email you@example.com
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const UNKNOWN = "UNKNOWN";
const PRICE = 197;
const SKU = "A";
const ROOT = dirname(fileURLToPath(import.meta.url));

function nowET() {
  return (
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date()) + " ET"
  );
}

function parseArgs(argv) {
  const out = { url: "", name: "", city: "", email: "" };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    const next = argv[i + 1];
    if (a === "--url" && next) { out.url = next; i++; }
    else if (a === "--name" && next) { out.name = next; i++; }
    else if (a === "--city" && next) { out.city = next; i++; }
    else if (a === "--email" && next) { out.email = next; i++; }
    else if (a === "--help" || a === "-h") { out.help = true; }
  }
  return out;
}

function slugify(s) {
  const t = String(s || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return t || "intake";
}

function nameFromMapsUrl(url) {
  if (!url) return "";
  try {
    const u = new URL(url);
    const m = u.pathname.match(/\/place\/([^/@]+)/);
    if (m) return decodeURIComponent(m[1].replace(/\+/g, " ")).trim();
    const q = u.searchParams.get("q") || u.searchParams.get("query");
    if (q) return q.trim();
  } catch {
    /* not a URL */
  }
  return "";
}

async function fetchPublic(url) {
  if (!url) {
    return { ok: false, status: 0, reason: "No GBP URL in intake", html: null };
  }
  try {
    const res = await fetch(url, {
      redirect: "follow",
      signal: AbortSignal.timeout(12000),
      headers: {
        Accept: "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "MapGapLocalAudit/0.1 (local prototype; public page only)",
      },
    });
    const html = await res.text();
    if (!res.ok) {
      return { ok: false, status: res.status, reason: "HTTP " + res.status, html: null };
    }
    return { ok: true, status: res.status, reason: "fetched " + html.length + " bytes", html };
  } catch (err) {
    return {
      ok: false,
      status: 0,
      reason: "fetch blocked or failed: " + (err && err.message ? err.message : String(err)),
      html: null,
    };
  }
}

function metaContent(html, key) {
  const re = new RegExp(
    "<meta[^>]+(?:property|name)=[\"']" + key + "[\"'][^>]*content=[\"']([^\"']+)[\"']",
    "i"
  );
  const re2 = new RegExp(
    "<meta[^>]+content=[\"']([^\"']+)[\"'][^>]*(?:property|name)=[\"']" + key + "[\"']",
    "i"
  );
  const m = html.match(re) || html.match(re2);
  return m ? decodeEntities(m[1]).trim() : "";
}

function decodeEntities(s) {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

function pickLd(html) {
  const re = /<script[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(html))) {
    let data;
    try {
      data = JSON.parse(m[1].trim());
    } catch {
      continue;
    }
    const nodes = [];
    const walk = (n) => {
      if (!n) return;
      if (Array.isArray(n)) { n.forEach(walk); return; }
      if (typeof n === "object") {
        nodes.push(n);
        if (n["@graph"]) walk(n["@graph"]);
      }
    };
    walk(data);
    for (const n of nodes) {
      const t = n["@type"];
      const types = Array.isArray(t) ? t : [t];
      if (types.some((x) => /LocalBusiness|HVACBusiness|Plumber|Electrician|HomeAndConstructionBusiness|ProfessionalService|Store/i.test(String(x || "")))) {
        return n;
      }
    }
  }
  return null;
}

function napFromLd(ld) {
  if (!ld) return UNKNOWN;
  const name = ld.name || "";
  let addr = "";
  const a = ld.address;
  if (typeof a === "string") addr = a;
  else if (a && typeof a === "object") {
    addr = [a.streetAddress, a.addressLocality, a.addressRegion, a.postalCode]
      .filter(Boolean)
      .join(", ");
  }
  const phone = ld.telephone || "";
  const parts = [name, addr, phone].filter(Boolean);
  return parts.length ? parts.join(" · ") : UNKNOWN;
}

function observedFromHtml(html) {
  const blank = {
    name: UNKNOWN,
    nap: UNKNOWN,
    website: UNKNOWN,
    primaryCategory: UNKNOWN,
    secondaries: UNKNOWN,
    stars: UNKNOWN,
    reviewCount: UNKNOWN,
    reviews30: UNKNOWN,
    reviews60: UNKNOWN,
    reviews90: UNKNOWN,
    posts90: UNKNOWN,
    services: UNKNOWN,
    storefrontOrSab: UNKNOWN,
    packPosition: UNKNOWN,
  };
  if (!html) return { ...blank, extractNote: "No HTML. All observed fields UNKNOWN." };

  const lower = html.slice(0, 20000).toLowerCase();
  if (
    lower.includes("before you continue") ||
    lower.includes("enable javascript") ||
    lower.includes("unusual traffic") ||
    lower.includes("consent.google")
  ) {
    return { ...blank, extractNote: "Interstitial or consent page. Fields not observed. UNKNOWN." };
  }

  const ld = pickLd(html);
  const ogTitle = metaContent(html, "og:title");
  const ogUrl = metaContent(html, "og:url");

  const out = { ...blank, extractNote: "Conservative public parse. Unseen fields stay UNKNOWN." };

  if (ld && ld.name) out.name = String(ld.name);
  else if (ogTitle && !/^google(\s|$)/i.test(ogTitle) && ogTitle.toLowerCase() !== "google maps") {
    out.name = ogTitle.replace(/\s*[-|–].*$/, "").trim() || UNKNOWN;
  }

  if (ld) out.nap = napFromLd(ld);

  if (ld && ld.url) out.website = String(ld.url);
  else if (ogUrl && !/google\.(com|com\/maps)/i.test(ogUrl)) out.website = ogUrl;

  if (ld && ld.aggregateRating && typeof ld.aggregateRating === "object") {
    const ar = ld.aggregateRating;
    if (ar.ratingValue != null && String(ar.ratingValue).trim() !== "") out.stars = String(ar.ratingValue);
    if (ar.reviewCount != null && String(ar.reviewCount).trim() !== "") out.reviewCount = String(ar.reviewCount);
  }

  // Do not scrape loose digits. 30/60/90, posts, services, categories, competitors
  // are not reliable in static Maps HTML — leave UNKNOWN.
  return out;
}

function unknownCompetitor(slot) {
  return {
    slot,
    name: UNKNOWN,
    gbpUrl: UNKNOWN,
    primaryCategory: UNKNOWN,
    secondaries: UNKNOWN,
    stars: UNKNOWN,
    reviewCount: UNKNOWN,
    reviews30: UNKNOWN,
    reviews60: UNKNOWN,
    reviews90: UNKNOWN,
    posts90: UNKNOWN,
    services: UNKNOWN,
    packPosition: UNKNOWN,
  };
}

function buildReport(intake, fetchInfo, observed) {
  const name =
    (intake.name && intake.name.trim()) ||
    (observed.name !== UNKNOWN ? observed.name : "") ||
    nameFromMapsUrl(intake.url) ||
    UNKNOWN;

  const snapshot = {
    name,
    nap: observed.nap,
    gbpUrl: intake.url || UNKNOWN,
    website: observed.website,
    primaryCategory: observed.primaryCategory,
    secondaries: observed.secondaries,
    storefrontOrSab: observed.storefrontOrSab,
    stars: observed.stars,
    reviewCount: observed.reviewCount,
    reviews30: observed.reviews30,
    reviews60: observed.reviews60,
    reviews90: observed.reviews90,
    posts90: observed.posts90,
    services: observed.services,
    snapshotTime: nowET(),
    fetchStatus: fetchInfo.ok
      ? "public fetch ok — unseen fields still UNKNOWN"
      : "fetch blocked or failed — " + fetchInfo.reason,
  };

  const thisWeek = [];
  const later = [];
  // Only emit actions that name an observed field. With a blocked fetch there are none.
  if (!fetchInfo.ok || observed.primaryCategory === UNKNOWN) {
    later.push("Re-run after a public listing page is readable; do not pay for a guess.");
  }

  return {
    sku: SKU,
    product: "Map Gap",
    title: "Map Pack Audit",
    price: PRICE,
    example: false,
    generatedAt: nowET(),
    dataPolicy: "Public pages only. UNKNOWN if not observed. Numbers are never invented.",
    intake: {
      gbpUrl: intake.url || UNKNOWN,
      name: intake.name || nameFromMapsUrl(intake.url) || UNKNOWN,
      city: intake.city || UNKNOWN,
      email: intake.email || UNKNOWN,
    },
    snapshot,
    competitors: [unknownCompetitor(1), unknownCompetitor(2), unknownCompetitor(3)],
    missingCategories: [],
    thisWeek,
    later,
    unknownRule:
      "If a field was not visible on a public page at generation time, it is UNKNOWN. UNKNOWN is not zero and is not a ranking. We do not invent review counts, star ratings, map-pack positions, competitor names, or categories. A blocked fetch still emits this skeleton from intake so the file exists.",
    fetch: {
      ok: !!fetchInfo.ok,
      status: fetchInfo.status,
      reason: fetchInfo.reason,
    },
    extractNote: observed.extractNote || UNKNOWN,
  };
}

function usage() {
  return `Map Gap SKU A generator — public fetch only, never invents numbers.

  node generate.mjs --url "https://maps.google.com/..." --email you@example.com
  node generate.mjs --name "Shop Name" --city "Columbus" --email you@example.com

Writes reports/<slug>.json. Open report.html?src=reports/<slug>.json over HTTP.
If Google blocks the fetch, every observed field is UNKNOWN; intake still appears.
Price $197 locked. SKU A only.`;
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log(usage());
    process.exit(0);
  }
  if (!args.url && !(args.name && args.city)) {
    console.error(usage());
    process.exit(1);
  }

  const fetchInfo = await fetchPublic(args.url);
  const observed = observedFromHtml(fetchInfo.html);
  const report = buildReport(args, fetchInfo, observed);

  const slug = slugify(
    [args.city || "", args.name || nameFromMapsUrl(args.url) || "intake"].filter(Boolean).join("-")
  );
  const dir = join(ROOT, "reports");
  mkdirSync(dir, { recursive: true });
  const outPath = join(dir, slug + ".json");
  writeFileSync(outPath, JSON.stringify(report, null, 2) + "\n");

  console.log("Wrote " + outPath);
  console.log("Fetch: " + fetchInfo.reason);
  console.log("Open:  http://127.0.0.1:8080/report.html?src=reports/" + slug + ".json");
  if (!fetchInfo.ok) {
    console.log("Observed fields are UNKNOWN (fetch blocked). Intake was still recorded. No numbers invented.");
  }
}

main();
