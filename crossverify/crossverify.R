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
  if (!is.na(seed)) set.seed(seed)   # match the Python seed for reproducibility
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
