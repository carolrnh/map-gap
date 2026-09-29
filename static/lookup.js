(function () {
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || form.tagName !== "FORM") return;
    var action = form.getAttribute("action") || "";
    if (action.indexOf("/lookup") === -1) return;
    var btn = form.querySelector("button[type='submit'], button:not([type])");
    if (!btn) return;
    if (form.dataset.submitted === "1") {
      e.preventDefault();
      return;
    }
    form.dataset.submitted = "1";
    btn.setAttribute("aria-disabled", "true");
    btn.setAttribute("aria-busy", "true");
    btn.textContent = "Checking your public listing…";
    var note = form.querySelector(".lookup-status");
    if (!note) {
      note = document.createElement("p");
      note.className = "hint lookup-status";
      note.setAttribute("role", "status");
      btn.insertAdjacentElement("afterend", note);
    }
    note.textContent = "Reading reviews, categories and competitors near you, usually 5–20 seconds.";
    // Disable on the next turn so this submit is not cancelled.
    window.setTimeout(function () {
      btn.disabled = true;
    }, 0);
  });
})();
