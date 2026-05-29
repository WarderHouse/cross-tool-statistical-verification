# Live demo (R Shiny)

An interactive "watch it verify" demo of the tool. It reproduces the bundled
mtcars example (`mpg ~ wt + hp`) and shows the six-phase verification reacting
as you switch the R replication between a correct version and two realistic
bugs. It is a teaching aid, not the tool itself: the command-line tool in the
parent directory is what you run on real analyses.

**Hosted:** <https://olivercrocco.shinyapps.io/ctsv-demo/>

## What it shows

- **Correct** (`mpg ~ wt + hp`) — every statistic matches across Python and R; the run passes.
- **Dropped predictor** (`mpg ~ wt`) — the `hp` statistics go missing and the model changes; the cross-tool phase catches it.
- **Mislabeled variable** (`mpg ~ wt + qsec`, reported under the `hp` name) — every value is present but several disagree; only triangulation reveals it.

A useful lesson is visible in the buggy modes: the internal consistency checks
can still pass while the two tools disagree. That is exactly why cross-tool
triangulation exists.

## Run it locally

Requires R with the `shiny` package:

```r
install.packages("shiny")     # one time
shiny::runApp("demo")         # from the repository root
```

The Python column is the verified output of `analysis.py` (statsmodels), held as
a fixed reference in `verify_logic.R`; the R column is computed live. The demo
runs no code that a visitor types in.

## Deploy to shinyapps.io (free tier)

```r
install.packages("rsconnect")
rsconnect::setAccountInfo(name = "<account>", token = "<token>", secret = "<secret>")
rsconnect::deployApp(appDir = "demo", appName = "ctsv-demo")
```

The free tier allows a handful of apps and a monthly active-hour budget, which is
ample for a demo. Once deployed, link it from the project README and from
olivercrocco.com/tools.

## Files

- `app.R` — the Shiny UI and server (depends only on `shiny`).
- `verify_logic.R` — the comparison and check logic, in pure base R so it can be
  tested on its own.
