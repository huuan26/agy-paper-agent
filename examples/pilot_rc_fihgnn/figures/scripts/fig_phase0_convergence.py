"""Two-panel Phase 0 numerical verification plot grounded in contract/experimental_log.md."""

import matplotlib.pyplot as plt

dyadic_levels = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
dyadic_errors = [
    0.03555555555555555,
    0.018713450292397654,
    0.009609609609609607,
    0.00487062404870624,
    0.002452107279693486,
    0.0012302960399846212,
    0.0006162141344117079,
    0.0003083742892936301,
    0.00015425403711737763,
    7.714375256141365e-05,
    3.8576061143056904e-05,
    1.9289076957389223e-05,
]

horizons_k = [1, 3, 12]
mc_p01 = [0.90107, 0.96420, 0.99077]
th_p01 = [0.90000, 0.96300, 0.99074]
mc_p03 = [0.70086, 0.86012, 0.96464]
th_p03 = [0.70000, 0.86100, 0.96429]
mc_p06 = [0.40019, 0.60927, 0.87739]
th_p06 = [0.40000, 0.60800, 0.87527]

figsize = (9.2, 3.6)
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize, dpi=300)

ax1.semilogy(
    dyadic_levels, dyadic_errors, marker="o", lw=1.6, color="#1f4e79", label="Empirical error"
)
ax1.set_xlabel("Dyadic refinement level $m$")
ax1.set_ylabel("Absolute hedging discrepancy")
ax1.set_title("(a) Proposition 2 $O(\\Delta)$ Convergence (order = 0.999922)", fontsize=9.5)
ax1.grid(True, which="both", linestyle="--", alpha=0.4)
ax1.legend(frameon=False, fontsize=8.5)

ax2.plot(horizons_k, th_p01, "--", color="#1b7837", lw=1.4, label="Theory ($p=0.1$)")
ax2.plot(horizons_k, mc_p01, "o", color="#1b7837", ms=5, label="400k MC ($p=0.1$)")
ax2.plot(horizons_k, th_p03, "--", color="#2166ac", lw=1.4, label="Theory ($p=0.3$)")
ax2.plot(horizons_k, mc_p03, "s", color="#2166ac", ms=5, label="400k MC ($p=0.3$)")
ax2.plot(horizons_k, th_p06, "--", color="#b2182b", lw=1.4, label="Theory ($p=0.6$)")
ax2.plot(horizons_k, mc_p06, "^", color="#b2182b", ms=5, label="400k MC ($p=0.6$)")
ax2.set_xticks(horizons_k)
ax2.set_xlabel("Holding horizon $k$ (5m bars)")
ax2.set_ylabel("Multi-horizon variance ratio")
ax2.set_title("(b) Lemma 3 Analytic vs. 400k Monte Carlo", fontsize=9.5)
ax2.grid(True, linestyle="--", alpha=0.4)
ax2.legend(frameon=False, fontsize=7.5, ncol=2, loc="lower right")

fig.tight_layout()
