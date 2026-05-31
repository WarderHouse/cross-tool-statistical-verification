# Worked example (R side): the independent replication of analysis.py.
# Emits the SAME statistic names so the harness can compare them one-to-one.
source(Sys.getenv("CROSSVERIFY_R"))
args <- cv_args()
d <- read.csv(args$data, stringsAsFactors = FALSE)

fit <- lm(mpg ~ wt + hp, data = d)
s <- summary(fit)
co <- s$coefficients

cv_emit(list(
  n_obs          = nrow(d),
  model_r2       = s$r.squared,
  coef_intercept = co["(Intercept)", "Estimate"],
  coef_wt        = co["wt", "Estimate"],
  coef_hp        = co["hp", "Estimate"],
  se_wt          = co["wt", "Std. Error"],
  se_hp          = co["hp", "Std. Error"],
  p_wt           = co["wt", "Pr(>|t|)"],
  p_hp           = co["hp", "Pr(>|t|)"],
  resid_sum      = sum(residuals(fit)),
  mean_mpg       = mean(d$mpg)
), args$out)
