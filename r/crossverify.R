# crossverify.R — helpers an R replication uses to talk to the verifier.
#
# Source this at the top of your R script:
#     source(Sys.getenv("CROSSVERIFY_R"))
# Then read the harness-supplied arguments with cv_args() and return your key
# statistics with cv_emit(). The harness invokes your script as:
#     Rscript your_script.R <data_csv> <out_json> <seed>

cv_args <- function() {
  a <- commandArgs(trailingOnly = TRUE)
  seed <- if (length(a) >= 3 && nzchar(a[3])) as.integer(a[3]) else NA_integer_
  # NOTE: this seeds THIS R session's RNG, but R and Python use different random
  # number generators, so a shared integer seed does NOT produce the same random
  # stream across the two tools. Cross-tool (Phase 5) comparison is therefore
  # meaningful only for deterministic estimators, not seed-matched random draws.
  # (A seed does make a same-tool re-run, Phase 4, reproducible.)
  if (!is.na(seed)) set.seed(seed)
  list(data = a[1], out = a[2], seed = seed)
}

cv_emit <- function(results, path) {
  if (!requireNamespace("jsonlite", quietly = TRUE)) {
    stop("crossverify: the R package 'jsonlite' is required. install.packages('jsonlite')")
  }
  # Coerce logicals to 0/1 and everything else to numeric; emit at full precision.
  flat <- lapply(results, function(x) if (is.logical(x)) as.integer(x) else as.numeric(x))
  jsonlite::write_json(flat, path = path, auto_unbox = TRUE, digits = NA)
}
