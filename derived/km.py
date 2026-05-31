"""
Kaplan-Meier survival estimator (from scratch — no lifelines dependency).

The product-limit estimator:

    S(t) = ∏_{t_i <= t} (1 - d_i / n_i)

where, at each distinct event time t_i, d_i is the number of events (deaths)
and n_i is the number at risk just before t_i. Censored observations leave the
risk set without contributing an event.

Variance via **Greenwood's formula**:

    Var(S(t)) = S(t)^2 * Σ_{t_i <= t}  d_i / (n_i * (n_i - d_i))

Confidence intervals on the *median* are derived by inverting the **log-log**
(complementary log-log) pointwise confidence band, which is preferred over the
plain (linear) CI for small samples because it respects the [0, 1] bounds of a
probability. For each event time we compute a 95% band on S(t); the CI bounds on
the median are the earliest times at which the upper/lower bands cross 0.5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from derived.rwos import SurvivalRecord

Z_95 = 1.959963984540054  # two-sided 95% normal quantile


@dataclass
class KMResult:
    """Result of a Kaplan-Meier fit."""

    times: list[float]
    survival_prob: list[float]
    n_at_risk: list[int]
    n_events: list[int]
    median_os_days: float | None
    ci_lower: float | None  # 95% CI lower bound on median (log-log / Greenwood)
    ci_upper: float | None


def kaplan_meier(survival_records: list[SurvivalRecord]) -> KMResult:
    """
    Fit a Kaplan-Meier curve over a set of :class:`SurvivalRecord`.

    The step function returned starts implicitly at S(0)=1; the ``times`` list
    contains the distinct event/censor times where the risk set changes, in
    ascending order. ``survival_prob[i]`` is S at ``times[i]`` (post-step).
    """
    if not survival_records:
        return KMResult([], [], [], [], None, None, None)

    # Aggregate by distinct time: count events and total observations leaving.
    events_at: dict[int, int] = {}
    leaving_at: dict[int, int] = {}  # events + censors (both leave the risk set)
    for r in survival_records:
        t = r.os_days
        leaving_at[t] = leaving_at.get(t, 0) + 1
        if r.event == 1:
            events_at[t] = events_at.get(t, 0) + 1

    distinct_times = sorted(leaving_at.keys())
    n = len(survival_records)

    times: list[float] = []
    survival_prob: list[float] = []
    n_at_risk: list[int] = []
    n_events: list[int] = []

    surv = 1.0
    at_risk = n
    greenwood_sum = 0.0  # running Σ d_i / (n_i (n_i - d_i))
    # Track variance per step so we can build the log-log band.
    var_terms: list[float] = []

    for t in distinct_times:
        d = events_at.get(t, 0)
        n_i = at_risk
        if d > 0 and n_i > 0:
            surv *= 1.0 - d / n_i
            if n_i - d > 0:
                greenwood_sum += d / (n_i * (n_i - d))
        times.append(float(t))
        survival_prob.append(surv)
        n_at_risk.append(n_i)
        n_events.append(d)
        var_terms.append(greenwood_sum)
        at_risk -= leaving_at[t]

    median = _median_from_steps(times, survival_prob)
    ci_lower, ci_upper = _median_ci_loglog(times, survival_prob, var_terms)

    return KMResult(
        times=times,
        survival_prob=survival_prob,
        n_at_risk=n_at_risk,
        n_events=n_events,
        median_os_days=median,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
    )


def greenwood_variance(survival_records: list[SurvivalRecord], at_time: float) -> float:
    """
    Greenwood variance of S(t) at a given time. Always >= 0.

    Exposed for testing the variance machinery directly.
    """
    res = kaplan_meier(survival_records)
    # Re-derive the variance at the requested time from the step function.
    if not res.times:
        return 0.0
    surv = 1.0
    at_risk = len(survival_records)
    gw = 0.0
    events_at: dict[int, int] = {}
    leaving_at: dict[int, int] = {}
    for r in survival_records:
        leaving_at[r.os_days] = leaving_at.get(r.os_days, 0) + 1
        if r.event == 1:
            events_at[r.os_days] = events_at.get(r.os_days, 0) + 1
    for t in sorted(leaving_at.keys()):
        if t > at_time:
            break
        d = events_at.get(t, 0)
        if d > 0 and at_risk > 0:
            surv *= 1.0 - d / at_risk
            if at_risk - d > 0:
                gw += d / (at_risk * (at_risk - d))
        at_risk -= leaving_at[t]
    var = surv * surv * gw
    return max(var, 0.0)


def _median_from_steps(times: list[float], survival_prob: list[float]) -> float | None:
    """
    Median survival = first time at which S(t) <= 0.5.

    Returns None when the curve never reaches 0.5 (all/mostly censored).
    """
    for t, s in zip(times, survival_prob, strict=True):
        if s <= 0.5:
            return t
    return None


def _median_ci_loglog(
    times: list[float],
    survival_prob: list[float],
    var_terms: list[float],
) -> tuple[float | None, float | None]:
    """
    95% CI on the median via the log-log transformed pointwise band.

    For S(t) with Greenwood sum V(t) = Σ d_i/(n_i(n_i-d_i)), the log-log band is

        S(t) ^ exp(± z * sqrt(V(t)) / log(S(t)))

    The CI bounds on the median are the earliest times where the lower / upper
    band, respectively, fall to or below 0.5.
    """
    lower_band: list[float] = []
    upper_band: list[float] = []
    for s, v in zip(survival_prob, var_terms, strict=True):
        if s >= 1.0 or s <= 0.0 or v <= 0.0:
            # Degenerate: band collapses to the point estimate.
            lower_band.append(s)
            upper_band.append(s)
            continue
        log_s = math.log(s)
        se = math.sqrt(v)
        c = Z_95 * se / log_s  # log_s < 0
        # log-log band; exp(c) and exp(-c) swap which is the upper bound
        # because log_s is negative.
        b1 = s ** math.exp(c)
        b2 = s ** math.exp(-c)
        lower_band.append(min(b1, b2))
        upper_band.append(max(b1, b2))

    # Lower CI bound on the median: the earliest plausible median → comes from
    # the LOWER survival band (pessimistic survival drops to 0.5 soonest).
    # Upper CI bound: the latest plausible median → from the UPPER band
    # (optimistic survival stays above 0.5 longest).
    ci_lower = _median_from_steps(times, lower_band)
    ci_upper = _median_from_steps(times, upper_band)
    return ci_lower, ci_upper
