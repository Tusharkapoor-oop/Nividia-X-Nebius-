/* UpgradePilot web UI: runs list, run detail with live SSE, bench table. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var source = null;
  var activeRunId = null;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  function setStatus(node, message, tone) {
    node.textContent = message;
    if (tone) {
      node.setAttribute("data-tone", tone);
    } else {
      node.removeAttribute("data-tone");
    }
  }

  function statusPill(status) {
    var pill = el("span", "status-pill", status);
    pill.setAttribute("data-status", status);
    return pill;
  }

  function closeStream() {
    if (source) { source.close(); source = null; }
  }

  /* ---------- runs list ---------- */

  function renderRuns(runs) {
    var body = $("runs-body");
    body.textContent = "";
    $("runs-empty").hidden = runs.length > 0;
    $("runs-table").hidden = runs.length === 0;

    runs.forEach(function (run) {
      var row = el("tr");

      var idCell = el("td");
      idCell.appendChild(el("code", null, run.run_id));
      if (run.error) { idCell.appendChild(el("div", "hint", run.error)); }
      row.appendChild(idCell);

      row.appendChild(el("td", null, "")).appendChild(statusPill(run.status));

      row.appendChild(el("td", null, run.package
        ? run.package + " → " + run.to_version
        : "—"));
      row.appendChild(el("td", null,
        run.iterations === null || run.iterations === undefined ? "—" : String(run.iterations)));
      row.appendChild(el("td", null,
        run.guard_clean === null || run.guard_clean === undefined ? "—" : (run.guard_clean ? "clean" : "violated")));

      var action = el("td");
      var button = el("button", "secondary", run.active ? "Watch" : "View");
      button.type = "button";
      button.setAttribute("aria-label", "View run " + run.run_id);
      button.addEventListener("click", function () { openRun(run.run_id, true); });
      action.appendChild(button);
      row.appendChild(action);

      body.appendChild(row);
    });
  }

  function loadRuns() {
    setStatus($("runs-status"), "Loading runs…");
    return fetch("/api/runs")
      .then(function (resp) {
        if (!resp.ok) { throw new Error("HTTP " + resp.status); }
        return resp.json();
      })
      .then(function (runs) {
        renderRuns(runs);
        setStatus($("runs-status"), runs.length + " run(s)");
      })
      .catch(function (err) {
        setStatus($("runs-status"), "Could not load runs: " + err.message, "error");
      });
  }

  /* ---------- run detail + SSE ---------- */

  function appendEvent(entry) {
    var item = el("li");
    var name = el("span", "ev-name", entry.event || "event");
    var status = entry.data && entry.data.status;
    if (status === "ok") { name.classList.add("ev-ok"); }
    else if (status === "failed") { name.classList.add("ev-failed"); }
    else { name.classList.add("ev-other"); }
    item.appendChild(name);
    var detail = (entry.data && entry.data.detail) || "";
    item.appendChild(document.createTextNode(": " + (detail || "")));
    if (entry.ts) { item.appendChild(el("span", "hint", "  " + entry.ts)); }
    $("event-log").appendChild(item);
    $("event-log").scrollTop = $("event-log").scrollHeight;
  }

  function renderDetail(detail) {
    var statusNode = $("detail-status");
    if (detail.error) {
      setStatus(statusNode, "Failed: " + detail.error, "error");
    } else if (detail.active) {
      setStatus(statusNode, "Running…", "busy");
    } else if (detail.report) {
      setStatus(statusNode, "Finished with status " + detail.report.status,
        detail.report.status === "GREEN" ? "ok" : "error");
    } else {
      setStatus(statusNode, "Preparing…", "busy");
    }

    var req = detail.report ? detail.report.request
      : (detail.setup ? { package: detail.setup.package, to_version: detail.setup.to_version } : null);
    $("detail-request").textContent = req && req.package
      ? "Upgrading " + req.package + " → " + req.to_version + "  ·  " + detail.run_id
      : detail.run_id;

    $("proof-card").textContent = detail.proof_card || "Not written yet.";
  }

  function openRun(runId, focusDetail) {
    activeRunId = runId;
    closeStream();
    $("run-detail").hidden = false;
    $("event-log").textContent = "";
    setStatus($("detail-status"), "Loading run…");

    fetch("/api/runs/" + encodeURIComponent(runId))
      .then(function (resp) {
        if (!resp.ok) { throw new Error("HTTP " + resp.status); }
        return resp.json();
      })
      .then(renderDetail)
      .catch(function (err) {
        setStatus($("detail-status"), "Could not load run: " + err.message, "error");
      });

    if (focusDetail) { $("detail-h").focus(); }
    streamEvents(runId);
  }

  function streamEvents(runId) {
    closeStream();
    source = new EventSource("/api/runs/" + encodeURIComponent(runId) + "/events");

    source.onmessage = function (msg) {
      try {
        appendEvent(JSON.parse(msg.data));
      } catch (err) {
        appendEvent({ event: "raw", data: { detail: msg.data } });
      }
    };

    source.addEventListener("run_error", function (msg) {
      var detail = {};
      try { detail = JSON.parse(msg.data); } catch (err) { /* keep raw */ }
      setStatus($("detail-status"), "Failed: " + (detail.error || "unknown error"), "error");
    });

    source.addEventListener("done", function () {
      closeStream();
      if (activeRunId !== runId) { return; }
      fetch("/api/runs/" + encodeURIComponent(runId))
        .then(function (resp) { return resp.ok ? resp.json() : null; })
        .then(function (detail) {
          if (detail && activeRunId === runId) { renderDetail(detail); }
        })
        .catch(function () { /* status already shown */ });
      loadRuns();
    });

    source.onerror = function () {
      /* EventSource auto-reconnects while the run is alive; a closed server
         surfaces here, and the "done" event closes the stream normally. */
    };
  }

  /* ---------- start run ---------- */

  function startRun(event) {
    event.preventDefault();
    var statusNode = $("start-status");
    var payload = {
      repo: $("repo").value.trim(),
      package: $("package").value.trim(),
      to_version: $("to-version").value.trim(),
      max_iterations: parseInt($("max-iterations").value, 10) || 5
    };

    if (!payload.repo || !payload.package || !payload.to_version) {
      setStatus(statusNode, "Repository, package, and target version are required.", "error");
      return;
    }

    var button = $("start-button");
    button.disabled = true;
    setStatus(statusNode, "Starting run…", "busy");

    fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (resp) {
        return resp.json().then(function (body) {
          return { ok: resp.ok, status: resp.status, body: body };
        });
      })
      .then(function (result) {
        button.disabled = false;
        if (!result.ok) {
          var detail = (result.body && result.body.detail) || ("HTTP " + result.status);
          setStatus(statusNode, detail, "error");
          return;
        }
        setStatus(statusNode, "Run " + result.body.run_id + " accepted.", "ok");
        loadRuns();
        openRun(result.body.run_id, true);
      })
      .catch(function (err) {
        button.disabled = false;
        setStatus(statusNode, "Could not start run: " + err.message, "error");
      });
  }

  /* ---------- benchmark ---------- */

  function cell(value) {
    return el("td", null, value === null || value === undefined || value === ""
      ? "—" : String(value));
  }

  function loadBench() {
    setStatus($("bench-status"), "Loading benchmark results…");
    fetch("/api/bench")
      .then(function (resp) {
        if (!resp.ok) { throw new Error("HTTP " + resp.status); }
        return resp.json();
      })
      .then(function (data) {
        if (!data.available) {
          setStatus($("bench-status"), "Benchmark module not found in this install.", "error");
          return;
        }
        var body = $("bench-body");
        body.textContent = "";
        data.rows.forEach(function (row) {
          var tr = el("tr");
          var th = el("th", null, row.case_id);
          th.scope = "row";
          tr.appendChild(th);
          tr.appendChild(cell(row.pre_status));
          tr.appendChild(cell(row.post_status));
          tr.appendChild(cell(row.pre_passed));
          tr.appendChild(cell(
            (row.post_failed === null ? "—" : row.post_failed) + "F / " +
            (row.post_errors === null ? "—" : row.post_errors) + "E"));
          tr.appendChild(cell(row.post_duration_s === null ? null : row.post_duration_s + "s"));
          body.appendChild(tr);
        });
        var empty = data.rows.length === 0;
        $("bench-table").hidden = empty;
        $("bench-empty").hidden = !empty;
        setStatus($("bench-status"), data.rows.length + " case(s) recorded");
      })
      .catch(function (err) {
        setStatus($("bench-status"), "Could not load benchmark results: " + err.message, "error");
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    $("run-form").addEventListener("submit", startRun);
    loadRuns();
    loadBench();
  });
})();
