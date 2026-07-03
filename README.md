# Language Entropy (lang_entropy)

Bigram cross-entropy scoring of strings against a language model.
Built for hunting DGA / C2 domains and other random-looking strings
(hashes, tokens) that hide among natural-language values.

Low score  = string looks like the modeled language (e.g. Polish).
High score = string looks random (does not fit the bigram model).

## What's inside

- `| entropy` - custom streaming search command (usable after any search pipe)
- Upload page (default app view) - converts a `bigram,count` frequency CSV
  into a conditional-probability model `q(c2|c1)` stored in `lookups/`
- Vendored `splunklib` in `bin/lib/` - no extra installation needed

## Install

1. Copy the `lang_entropy/` directory to `$SPLUNK_HOME/etc/apps/`
   (or install the packaged `.tar.gz` via Manage Apps > Install app from file).
2. Restart Splunk.
3. Open the app, go to the "Upload bigram model" page and upload your
   frequency CSV (e.g. name it `polish_bigrams` -> creates
   `polish_bigrams_probabilities.csv`).

The role uploading models needs write access to the app (admin/power by
default, see `metadata/default.meta`).

## Usage

    index=dns
    | entropy field=query
    | where entropy > 9

Options:

    | entropy field=<field>                          required
             lookup=<file.csv>                       default: polish_bigrams_probabilities.csv
             output=<fieldname>                      default: entropy
             floor=<float>                           default: 1e-7

Notes:

- Input is lowercased; spaces, dots, commas and hyphens are stripped
  before scoring, so full domain names can be passed directly.
- `floor` is the probability assigned to bigrams absent from the model
  (digits, foreign characters, impossible pairs). Keep it BELOW the
  smallest probability in your model - the upload page reports that value
  and warns if the default floor is too high.
- Values shorter than 2 characters after normalization get an empty score.
- Thresholds are data-dependent. Start by charting the score distribution
  of known-good traffic, then pick a cutoff (as with URL Toolbox's
  ut_shannon, expect to tune it per environment).

## Model CSV formats

Frequency input (what you upload):

    bigram,count
    ie,1962799
    ni,1516329

Probability output (what the entropy command reads):

    bigram,probability
    ie,0.7358494739430875
    ni,0.5989299806851441

Probabilities are conditional: for each first character, the values of
all bigrams starting with it sum to 1.

## Why a custom command and not eval entropy(...)

Classic SPL does not support user-defined eval functions - there is no
supported extension point for them (the community has asked for years).
The closest supported equivalents are a custom streaming command (this
app) or an external lookup. The streaming command composes with eval
naturally:

    | entropy field=domain | eval suspicious=if(entropy>9, "yes", "no")

## Entropy lab (view)

Interactive view for exploring scores, backed by the entropy_lab REST
endpoint (same scoring code as the `entropy` command):

1. Maximum possible entropy for a user-supplied floor: -log2(floor).
2. Single-string scoring against every model in lookups/.
3. Batch scoring: upload a file with strings one per line (max 10 000),
   get per-model summary statistics (min, max, mean, median, std dev,
   p95, counts) above a results table, and download all rows as CSV.
   The table displays up to 1 000 rows; the CSV always contains all.
