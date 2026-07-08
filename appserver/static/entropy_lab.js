require([
    "jquery",
    "splunkjs/mvc/simplexml/ready!"
], function ($) {
    "use strict";

    /* --- Splunk helpers without the splunk.util dependency --- */

    function splunkdPath() {
        if (window.$C && window.$C.SPLUNKD_PATH) {
            return window.$C.SPLUNKD_PATH;
        }
        var seg = window.location.pathname.split("/")[1] || "en-US";
        return "/" + seg + "/splunkd/__raw";
    }

    function formKey() {
        if (window.$C && window.$C.FORM_KEY) {
            return window.$C.FORM_KEY;
        }
        var m = document.cookie.match(/splunkweb_csrf_token_[^=]*=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : "";
    }

    var ENDPOINT = splunkdPath() + "/services/entropy_lab";
    var lastBatch = null; // kept for CSV export
    var DISPLAY_CAP = 1000;

    function get(params) {
        return $.ajax({
            url: ENDPOINT + "?" + $.param(params),
            type: "GET",
            dataType: "json"
        });
    }

    function post(params, body) {
        return $.ajax({
            url: ENDPOINT + "?" + $.param(params),
            type: "POST",
            dataType: "json",
            data: JSON.stringify(body),
            contentType: "application/json",
            processData: false,
            headers: { "X-Splunk-Form-Key": formKey() }
        });
    }

    function errorText(xhr) {
        try {
            var body = JSON.parse(xhr.responseText);
            if (body && body.error) { return body.error; }
        } catch (e) { /* fall through */ }
        return "Request failed (HTTP " + xhr.status + "). If this is 404, " +
               "restart Splunk - REST endpoints from restmap.conf are only " +
               "registered at startup.";
    }

    function fmt(v) {
        return (v === null || v === undefined) ? "\u2014" : v;
    }

    /* ---------- Section 1: maximum possible entropy ---------- */

    function loadMaxEntropy() {
        var floor = ($("#lab-max-floor").val() || "1e-7").trim();
        get({ action: "maxentropy", floor: floor }).done(function (data) {
            if (typeof data === "string") { data = JSON.parse(data); }
            $("#lab-max-value").removeClass("lab-err")
                .text(data.max_entropy_bits.toFixed(4) + " bits/bigram");
            $("#lab-max-formula").text(
                "-log2(" + data.floor + ") \u2014 same for every string length \u2265 2"
            );
        }).fail(function (xhr) {
            $("#lab-max-value").addClass("lab-err").text(errorText(xhr));
            $("#lab-max-formula").text("");
        });
    }

    /* ---------- Section 2: single string ---------- */

    function scoreSingle() {
        var s = $("#lab-single-input").val();
        var out = $("#lab-single-out").empty();
        if (!s || !s.trim()) {
            out.append($("<p>").addClass("lab-err").text("Enter a string first."));
            return;
        }
        post({ action: "score" }, { strings: [s] }).done(function (data) {
            if (typeof data === "string") { data = JSON.parse(data); }
            var table = $("<table>").addClass("lab-table");
            table.append($("<thead>").append(
                $("<tr>")
                    .append($("<th>").text("Model"))
                    .append($("<th>").text("Entropy (bits/bigram)"))
            ));
            var tbody = $("<tbody>").appendTo(table);
            data.models.forEach(function (name, i) {
                $("<tr>")
                    .append($("<td>").text(name))
                    .append($("<td>").text(fmt(data.rows[0].scores[i])))
                    .appendTo(tbody);
            });
            out.append($("<div>").addClass("lab-scroll").append(table));
        }).fail(function (xhr) {
            out.append($("<p>").addClass("lab-err").text(errorText(xhr)));
        });
    }

    /* ---------- Section 3: batch from file ---------- */

    var STAT_KEYS = [
        ["scored", "Scored"], ["too_short", "Too short"],
        ["min", "Min"], ["max", "Max"], ["mean", "Mean"],
        ["median", "Median"], ["stdev", "Std dev"], ["p95", "P95"]
    ];

    var sortCol = null;  // -1 = string column, 0..N-1 = model score columns
    var sortDir = 1;     // 1 = ascending, -1 = descending

    function sortRows() {
        if (sortCol === null || !lastBatch) { return; }
        lastBatch.rows.sort(function (a, b) {
            if (sortCol === -1) {
                return sortDir * String(a.string).localeCompare(String(b.string));
            }
            var va = a.scores[sortCol];
            var vb = b.scores[sortCol];
            var na = (va === null || va === undefined);
            var nb = (vb === null || vb === undefined);
            if (na || nb) { return na - nb; }  // empty scores always last
            return sortDir * (va - vb);
        });
    }

    function headerCell(label, colIndex) {
        var arrow = "";
        if (sortCol === colIndex) {
            arrow = sortDir === 1 ? " \u25B2" : " \u25BC";
        }
        return $("<th>")
            .text(label + arrow)
            .css("cursor", "pointer")
            .attr("title", "Click to sort")
            .on("click", function () {
                if (sortCol === colIndex) {
                    sortDir = -sortDir;
                } else {
                    sortCol = colIndex;
                    sortDir = 1;
                }
                sortRows();
                renderTable(lastBatch);
            });
    }

    function renderStats(data) {
        var container = $("#lab-batch-stats").empty();
        data.models.forEach(function (name) {
            var s = data.stats[name];
            var block = $("<div>").addClass("lab-model-block");
            block.append($("<h4>").text(name));
            var cards = $("<div>").addClass("lab-stats").appendTo(block);
            STAT_KEYS.forEach(function (pair) {
                var v = s[pair[0]];
                if (typeof v === "number" && !Number.isInteger(v)) {
                    v = v.toFixed(4);
                }
                $("<div>").addClass("lab-stat-card")
                    .append($("<div>").addClass("k").text(pair[1]))
                    .append($("<div>").addClass("v").text(fmt(v)))
                    .appendTo(cards);
            });
            container.append(block);
        });
    }

    function renderTable(data) {
        var thead = $("#lab-batch-table thead").empty();
        var tbody = $("#lab-batch-table tbody").empty();
        var hr = $("<tr>").append(headerCell("String", -1));
        data.models.forEach(function (name, i) {
            hr.append(headerCell(name, i));
        });
        thead.append(hr);

        var shown = Math.min(data.rows.length, DISPLAY_CAP);
        for (var i = 0; i < shown; i++) {
            var row = data.rows[i];
            var tr = $("<tr>").append($("<td>").text(row.string));
            row.scores.forEach(function (score) {
                tr.append($("<td>").text(fmt(score)));
            });
            tbody.append(tr);
        }
        $("#lab-batch-info").removeClass("lab-err").text(
            (data.rows.length > DISPLAY_CAP
                ? "Showing first " + DISPLAY_CAP + " of " + data.rows.length +
                  " rows. The CSV download contains all rows."
                : data.rows.length + " rows.") +
            " Floor used: " + data.floor + "."
        );
    }

    function scoreBatch() {
        var fileInput = $("#lab-batch-file")[0];
        var info = $("#lab-batch-info");
        if (!fileInput.files || !fileInput.files.length) {
            info.addClass("lab-err").text("Choose a file first.");
            return;
        }
        var reader = new FileReader();
        reader.onerror = function () {
            info.addClass("lab-err").text("Could not read the selected file.");
        };
        reader.onload = function () {
            var strings = reader.result.split(/\r?\n/)
                .map(function (line) { return line.trim(); })
                .filter(function (line) { return line.length > 0; });
            if (!strings.length) {
                info.addClass("lab-err").text("File contains no non-empty lines.");
                return;
            }
            var body = { strings: strings };
            var floorRaw = ($("#lab-batch-floor").val() || "").trim();
            if (floorRaw) {
                var floorNum = Number(floorRaw);
                if (!isFinite(floorNum) || floorNum <= 0 || floorNum > 1) {
                    info.addClass("lab-err").text(
                        "Floor must be a number in (0, 1], e.g. 1e-8. Leave empty for the default."
                    );
                    return;
                }
                body.floor = floorNum;
            }
            info.removeClass("lab-err").text("Scoring " + strings.length + " strings\u2026");
            post({ action: "score" }, body).done(function (data) {
                if (typeof data === "string") { data = JSON.parse(data); }
                lastBatch = data;
                sortCol = null;
                sortDir = 1;
                renderStats(data);
                renderTable(data);
                $("#lab-batch-csv").show();
            }).fail(function (xhr) {
                info.addClass("lab-err").text(errorText(xhr));
            });
        };
        reader.readAsText(fileInput.files[0], "utf-8");
    }

    function csvField(value) {
        var s = String(value === null || value === undefined ? "" : value);
        return '"' + s.replace(/"/g, '""') + '"';
    }

    function downloadCsv() {
        if (!lastBatch) { return; }
        var lines = [];
        lines.push(["string"].concat(lastBatch.models).map(csvField).join(","));
        lastBatch.rows.forEach(function (row) {
            lines.push([row.string].concat(row.scores).map(csvField).join(","));
        });
        var blob = new Blob([lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "entropy_scores.csv";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(a.href);
    }

    /* ---------- init ---------- */

    try {
        $("#lab-max-btn").on("click", loadMaxEntropy);
        $("#lab-max-floor").on("change", loadMaxEntropy);
        $("#lab-single-btn").on("click", scoreSingle);
        $("#lab-batch-btn").on("click", scoreBatch);
        $("#lab-batch-csv").on("click", downloadCsv);
        loadMaxEntropy();
    } catch (e) {
        if (window.console) { console.error("entropy_lab init failed:", e); }
        $("#lab-max-value").addClass("lab-err")
            .text("Entropy lab failed to initialize: " + e.message);
    }
});
