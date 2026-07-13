require([
    "jquery",
    "splunkjs/mvc/simplexml/ready!"
], function ($) {
    "use strict";

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

    var ENDPOINT = splunkdPath() + "/services/entropy_upload";

    function showResult(kind, text) {
        $("#ent-result")
            .removeClass("ok err")
            .addClass(kind)
            .text(text);
    }

    function formatSuccess(data) {
        var lines = [
            "Model created: " + data.lookup,
            "Bigrams: " + data.bigrams +
                "   Contexts (first chars): " + data.contexts,
            "Skipped malformed rows: " + data.skipped_rows,
            "Smallest probability: " + Number(data.min_probability).toExponential(2),
            "",
            "Example SPL:",
            data.example_spl
        ];
        if (data.floor_hint) {
            lines.push("", "Note: " + data.floor_hint);
        }
        return lines.join("\n");
    }

    $("#ent-submit").on("click", function () {
        var name = ($("#ent-name").val() || "").trim();
        var fileInput = $("#ent-file")[0];

        if (!/^[A-Za-z0-9_\-]{1,64}$/.test(name)) {
            showResult("err", "Enter a model name (letters, digits, _ or -).");
            return;
        }
        if (!fileInput.files || !fileInput.files.length) {
            showResult("err", "Choose a CSV file first.");
            return;
        }

        var reader = new FileReader();
        reader.onerror = function () {
            showResult("err", "Could not read the selected file.");
        };
        reader.onload = function () {
            showResult("ok", "Uploading\u2026");
            $.ajax({
                url: ENDPOINT + "?name=" + encodeURIComponent(name),
                type: "POST",
                dataType: "json",
                data: reader.result,
                contentType: "text/csv",
                processData: false,
                headers: { "X-Splunk-Form-Key": formKey() }
            }).done(function (data) {
                if (typeof data === "string") {
                    try { data = JSON.parse(data); } catch (e) { /* keep */ }
                }
                showResult("ok", formatSuccess(data));
            }).fail(function (xhr) {
                var msg = "Upload failed (HTTP " + xhr.status + ")";
                try {
                    var body = JSON.parse(xhr.responseText);
                    if (body && body.error) { msg = body.error; }
                } catch (e) { /* keep default */ }
                showResult("err", msg);
            });
        };
        reader.readAsText(fileInput.files[0], "utf-8");
    });
});
