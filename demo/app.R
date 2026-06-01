# app.R — "watch it verify" live demo for cross-tool-statistical-verification.
#
# A single-file Shiny app (depends only on `shiny`). It reproduces the bundled
# mtcars example and shows the six-phase verification reacting as you switch the
# R replication between a correct version and two realistic bugs.
#
# Run locally:   install.packages("shiny"); shiny::runApp("demo")
# Deploy:        see demo/README.md (shinyapps.io, free tier)

library(shiny)
source("verify_logic.R")

fmt <- function(x) {
  if (length(x) == 0 || is.na(x)) return("—")
  if (x != 0 && (abs(x) < 1e-4 || abs(x) >= 1e6)) formatC(x, format = "e", digits = 3)
  else formatC(x, format = "g", digits = 6)
}

GREEN <- "#1a7f37"
RED <- "#cf222e"

MODES <- c(
  "Correct — mpg ~ wt + hp (matches the Python analysis)" = "correct",
  "Bug: a predictor was dropped — mpg ~ wt" = "dropped",
  "Bug: wrong variable reported as hp — mpg ~ wt + qsec" = "mislabeled"
)

MODE_LABEL <- c(
  correct = "correct (mpg ~ wt + hp)",
  dropped = "dropped predictor (mpg ~ wt)",
  mislabeled = "mislabeled variable (qsec reported as hp)"
)

ui <- fluidPage(
  tags$head(tags$style(HTML("
    body { max-width: 940px; margin: 0 auto; padding-bottom: 60px; }
    .muted { color: #6b6b6b; }
    .phase { border-top: 2px solid #e7e2da; padding-top: 6px; margin-top: 26px; }
    .phase h3 { margin: 2px 0 6px; }
    table.cmp { width: 100%; border-collapse: collapse;
                font-family: ui-monospace, Menlo, monospace; font-size: 13px; }
    table.cmp th, table.cmp td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee; }
    table.cmp th { color: #6b6b6b; font-weight: 600; }
    .verdict { padding: 14px 18px; border-radius: 6px; font-weight: 600; margin-top: 6px; }
    .verdict.pass { background: #e6f4ea; color: #1a7f37; border: 1px solid #1a7f37; }
    .verdict.fail { background: #fce8e6; color: #cf222e; border: 1px solid #cf222e; }
    .tag { font-family: ui-monospace, monospace; font-size: 12px; font-weight: 600; }
  "))),
  titlePanel("cross-tool-statistical-verification — live demo"),
  p(class = "muted",
    "A walk-through of the bundled mtcars example: an OLS regression ",
    tags$code("mpg ~ wt + hp"), " compared across Python and R. The Python column is the ",
    "reference output of ", tags$code("analysis.py"), " (statsmodels); the R column is computed ",
    "live. ",
    tags$a(href = "https://github.com/WarderHouse/cross-tool-statistical-verification",
           "View the tool on GitHub", target = "_blank")),
  sidebarLayout(
    sidebarPanel(
      width = 4,
      radioButtons("mode", "R replication", choices = MODES, selected = "correct"),
      numericInput("atol", "Match tolerance (absolute)", value = 1e-6, min = 0, step = 1e-6),
      p(class = "muted",
        "Switch the R replication to a buggy version and watch the cross-tool ",
        "comparison catch it. The internal checks can still pass while the tools ",
        "disagree — which is exactly why triangulation matters. This demo runs no ",
        "code you type in."),
      uiOutput("sidebarResult")
    ),
    mainPanel(
      width = 8,
      uiOutput("banner"),
      div(class = "phase", h3("Phase 1 — Data intake"),
          p(class = "muted", "The dataset as loaded: mtcars, 32 cars by 11 variables (first rows shown)."),
          tableOutput("intake")),
      div(class = "phase", h3("Phase 2 — Transformations"),
          p(class = "muted", "No prepare() step is declared; the analysis uses the raw data as loaded.")),
      div(class = "phase", h3("Phase 3 — Internal consistency"),
          p(class = "muted", "Each reported number is checked to be the kind of value it claims to be."),
          uiOutput("consistency")),
      div(class = "phase", h3("Phase 4 — Reproducibility"),
          uiOutput("repro")),
      div(class = "phase", h3("Phase 5 — Cross-tool triangulation"),
          p(class = "muted", "Python vs R, statistic by statistic, within tolerance."),
          uiOutput("compare")),
      div(class = "phase", h3("Phase 6 — Verdict"),
          uiOutput("verdict"), br(),
          downloadButton("dl", "Download verification log"))
    )
  ),
  p(class = "muted", style = "margin-top:24px; padding-top:16px; border-top:1px solid #e7e2da;",
    "Agreement means the result is implementation-independent, not necessarily ",
    "correct: you write both sides, so a shared mistake would agree too. The demo ",
    "shows what cross-tool checking can and cannot catch.")
)

server <- function(input, output, session) {
  res <- reactive({
    atol <- if (is.null(input$atol) || is.na(input$atol)) 1e-6 else input$atol
    r <- r_results(input$mode)
    list(r = r,
         cmp = compare_tools(r, atol = atol, rtol = 1e-6),
         cons = consistency_checks(r),
         repro = reproducible(input$mode))
  })

  output$banner <- renderUI({
    v <- verdict_of(res())
    div(class = paste("verdict", if (v$pass) "pass" else "fail"),
        if (v$pass)
          sprintf("PASS — all %d statistics matched across Python and R.", v$total)
        else
          sprintf("FAIL — %d of %d statistics matched. R replication: %s.",
                  v$matched, v$total, MODE_LABEL[[input$mode]]))
  })

  output$sidebarResult <- renderUI({
    v <- verdict_of(res())
    sty <- paste0("margin-top:14px;padding:10px 12px;border-radius:6px;text-align:center;",
                  "font-weight:600;font-size:14px;",
                  if (v$pass) "background:#e6f4ea;color:#1a7f37;border:1px solid #1a7f37;"
                  else "background:#fce8e6;color:#cf222e;border:1px solid #cf222e;")
    div(style = sty, sprintf("%s · %d/%d match", if (v$pass) "PASS" else "FAIL", v$matched, v$total))
  })

  output$intake <- renderTable(head(mtcars, 6), rownames = TRUE)

  output$consistency <- renderUI({
    cons <- res()$cons
    tags$ul(lapply(seq_len(nrow(cons)), function(i) {
      ok <- cons$pass[i]
      tags$li(tags$span(class = "tag", style = paste0("color:", if (ok) GREEN else RED, ";"),
                        if (ok) "PASS " else "FAIL "), cons$check[i])
    }))
  })

  output$repro <- renderUI({
    ok <- res()$repro
    p(tags$span(class = "tag", style = paste0("color:", if (ok) GREEN else RED, ";"),
                if (ok) "PASS " else "FAIL "),
      "Re-running the R analysis produced identical results.")
  })

  output$compare <- renderUI({
    cmp <- res()$cmp
    body <- lapply(seq_len(nrow(cmp)), function(i) {
      m <- isTRUE(cmp$match[i])
      label <- if (m) "match" else if (nzchar(cmp$note[i])) cmp$note[i] else "MISMATCH"
      tags$tr(
        tags$td(cmp$stat[i]), tags$td(fmt(cmp$python[i])), tags$td(fmt(cmp$r[i])),
        tags$td(fmt(cmp$delta[i])),
        tags$td(style = paste0("color:", if (m) GREEN else RED, ";font-weight:600;"), label))
    })
    tags$table(class = "cmp",
      tags$thead(tags$tr(tags$th("Statistic"), tags$th("Python"), tags$th("R"),
                         tags$th(HTML("|&Delta;|")), tags$th("Match"))),
      tags$tbody(body))
  })

  output$verdict <- renderUI({
    s <- res()
    matched <- sum(s$cmp$match); total <- nrow(s$cmp)
    pass <- overall_pass(s$cmp, s$cons, s$repro)
    div(class = paste("verdict", if (pass) "pass" else "fail"),
        if (pass)
          sprintf("PASS — all %d statistics matched within tolerance; the two implementations agree (the result is independent of either tool's defaults).", total)
        else
          sprintf("FAIL — %d of %d statistics matched. The implementations disagree; see Phase 5.", matched, total))
  })

  output$dl <- downloadHandler(
    filename = function() "verification_log.txt",
    content = function(file) {
      s <- res()
      tbl <- vapply(seq_len(nrow(s$cmp)), function(i) sprintf(
        "  %-16s %14s %14s   %s", s$cmp$stat[i], fmt(s$cmp$python[i]), fmt(s$cmp$r[i]),
        if (isTRUE(s$cmp$match[i])) "match" else if (nzchar(s$cmp$note[i])) s$cmp$note[i] else "MISMATCH"),
        character(1))
      writeLines(c(
        "cross-tool-statistical-verification — demo verification log",
        paste("R replication mode:", input$mode),
        "", "Phase 5 — cross-tool comparison (Python vs R):",
        sprintf("  %-16s %14s %14s   %s", "statistic", "python", "r", "match"), tbl,
        "", sprintf("Verdict: %s", if (overall_pass(s$cmp, s$cons, s$repro)) "PASS" else "FAIL")
      ), file)
    }
  )
}

shinyApp(ui, server)
