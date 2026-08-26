/* Map Gap — SKU A report renderer. Never invent numbers. UNKNOWN stays UNKNOWN. */
(function () {
  const UNKNOWN = "UNKNOWN";

  function isUnknown(v) {
    if (v == null || v === "") return true;
    if (Array.isArray(v) && v.length === 0) return true;
    const s = String(v).trim();
    return s === "" || s.toUpperCase() === UNKNOWN;
  }

  function cell(v, example) {
    if (isUnknown(v)) return '<span class="unk">UNKNOWN</span>';
    const extra = example ? ' <span class="ex">EXAMPLE</span>' : "";
    if (Array.isArray(v)) return escapeHtml(v.join(", ")) + extra;
    return escapeHtml(String(v)) + extra;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function listOrUnknown(items, example) {
    if (!items || !items.length) return '<p class="empty-note">None observed. <span class="unk">UNKNOWN</span> is not a measured gap.</p>';
    const tag = example ? ' <span class="ex">EXAMPLE</span>' : "";
    return "<ol class='actions'>" + items.map(function (x) {
      return "<li>" + escapeHtml(x) + tag + "</li>";
    }).join("") + "</ol>";
  }

  function competitorRows(report) {
    const you = report.snapshot || {};
    const comps = report.competitors || [];
    const example = !!report.example;
    const rows = [];
    rows.push(tr("You — " + (you.name || UNKNOWN), you, example));
    for (let i = 0; i < 3; i++) {
      const c = comps[i] || { name: UNKNOWN };
      rows.push(tr("C" + (i + 1) + " — " + (c.name || UNKNOWN), c, example));
    }
    return rows.join("");
  }

  function tr(label, b, example) {
    return "<tr>" +
      "<td>" + escapeHtml(label) + "</td>" +
      "<td>" + cell(b.primaryCategory || b.primary, example) + "</td>" +
      "<td>" + cell(b.secondaries, example) + "</td>" +
      "<td>" + cell(b.stars, example) + "</td>" +
      "<td>" + cell(b.reviewCount, example) + "</td>" +
      "<td>" + cell(b.packPosition, example) + "</td>" +
      "</tr>";
  }

  function missingTable(report) {
    const rows = report.missingCategories || [];
    const example = !!report.example;
    if (!rows.length) {
      return '<p class="empty-note">No missing categories listed — competitor categories were not observed, or none differed. Fields stay <span class="unk">UNKNOWN</span> rather than guessed.</p>';
    }
    return "<table><thead><tr><th>Category</th><th>Who has it</th><th>You offer it?</th><th>Rec</th></tr></thead><tbody>" +
      rows.map(function (r) {
        return "<tr><td>" + cell(r.category, example) + "</td><td>" + cell(r.who, example) +
          "</td><td>" + cell(r.offer, example) + "</td><td>" + cell(r.rec, example) + "</td></tr>";
      }).join("") + "</tbody></table>";
  }

  function snapshotTable(s, example) {
    const rows = [
      ["NAP", s.nap],
      ["GBP URL", s.gbpUrl],
      ["Website", s.website],
      ["Primary category", s.primaryCategory],
      ["Secondaries", s.secondaries],
      ["Storefront or SAB", s.storefrontOrSab],
      ["Stars", s.stars],
      ["Review count", s.reviewCount],
      ["Reviews last 30d", s.reviews30],
      ["Reviews last 60d", s.reviews60],
      ["Reviews last 90d", s.reviews90],
      ["Posts last 90d", s.posts90],
      ["Services listed", s.services],
      ["Snapshot time", s.snapshotTime],
      ["Fetch status", s.fetchStatus]
    ];
    return "<table><tbody>" + rows.map(function (r) {
      return "<tr><th>" + escapeHtml(r[0]) + "</th><td>" + cell(r[1], example) + "</td></tr>";
    }).join("") + "</tbody></table>";
  }

  function render(report) {
    const example = !!report.example;
    const s = report.snapshot || {};
    const intake = report.intake || {};
    const banner = example
      ? '<div class="banner">EXAMPLE DATA — not a real business. Numbers and competitors are sample layout only. Do not treat as a live audit.</div>'
      : '<div class="banner unk">Public-data report. Every field not seen on a public page is <span class="unk">UNKNOWN</span>. UNKNOWN is not zero. Numbers are never invented.</div>';

    const title = example ? "Map Gap — EXAMPLE Map Pack Report" : "Map Gap — Map Pack Report";
    const who = s.name || intake.name || intake.gbpUrl || "intake";

    document.title = title + " · " + who;

    return (
      banner +
      '<p class="muted">SKU A · Map Pack Audit · <span class="price">$197</span> · public GBP only · you keep ownership</p>' +
      "<h1>" + escapeHtml(title) + "</h1>" +
      "<p>Subject: <strong>" + escapeHtml(who) + "</strong>" +
      (intake.city ? " · " + escapeHtml(intake.city) : "") +
      (intake.email ? " · " + escapeHtml(intake.email) : "") +
      "</p>" +

      '<section class="section"><h2>1. Snapshot</h2>' +
      snapshotTable(s, example) +
      "</section>" +

      '<section class="section"><h2>2. Competitor table</h2>' +
      "<p class='muted'>You vs up to 3 map-pack competitors. Positions and names stay UNKNOWN unless observed on a public page this session.</p>" +
      "<table><thead><tr><th>Business</th><th>Primary</th><th>Secondaries</th><th>Stars</th><th>Reviews</th><th>Pack position</th></tr></thead><tbody>" +
      competitorRows(report) +
      "</tbody></table></section>" +

      '<section class="section"><h2>3. Missing categories</h2>' +
      "<p class='muted'>Categories a competitor listing showed that the subject listing did not. Only observed strings. Do not add a category you do not actually offer.</p>" +
      missingTable(report) +
      "</section>" +

      '<section class="section"><h2>4. This week vs later</h2>' +
      "<h3>This week</h3>" +
      listOrUnknown(report.thisWeek, example) +
      "<h3>Later</h3>" +
      listOrUnknown(report.later, example) +
      "</section>" +

      '<section class="section"><h2>5. UNKNOWN rule</h2>' +
      "<p>" + escapeHtml(report.unknownRule || defaultUnknownRule()) + "</p>" +
      "<p class='legal'>No fake reviews. No ownership transfer. No #1 promises. You keep the listing. No ranking is guaranteed.</p>" +
      "</section>"
    );
  }

  function defaultUnknownRule() {
    return "If a field was not visible on a public page at generation time, it is UNKNOWN. UNKNOWN is not zero and is not a ranking. We do not invent review counts, star ratings, map-pack positions, competitor names, or categories. A blocked fetch still emits this skeleton from intake so the file exists; it is not a paid audit of a live listing.";
  }

  function show(html) {
    const app = document.getElementById("app");
    if (app) app.innerHTML = html;
  }

  function parseEmbedded() {
    const el = document.getElementById("report-data");
    if (!el) return null;
    const raw = el.textContent.trim();
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (e) { return null; }
  }

  async function load() {
    const embedded = parseEmbedded();
    if (embedded) {
      show(render(embedded));
      return;
    }
    const params = new URLSearchParams(location.search);
    const src = params.get("src");
    if (src) {
      try {
        const res = await fetch(src);
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        show(render(data));
        return;
      } catch (e) {
        show('<div class="banner unk">Could not load ' + escapeHtml(src) + '. Serve this folder over HTTP and pass a JSON file generated by generate.mjs.</div>');
        return;
      }
    }
    show(
      '<div class="banner unk">No report loaded.</div>' +
      "<p>Open <a href='demo-report.html'>demo-report.html</a> for EXAMPLE layout, or run <code>node generate.mjs --url …</code> then <code>report.html?src=reports/&lt;slug&gt;.json</code>.</p>" +
      "<p>Empty renderer will not invent a business or any numbers.</p>"
    );
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load);
  else load();
})();
