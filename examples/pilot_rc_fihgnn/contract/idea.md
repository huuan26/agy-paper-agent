# Problem Statement

Intraday index futures markets exhibit higher-order, synchronous co-movements across the nearest futures contract, cash index, constituent equity basket, order-flow imbalance, and liquidity regimes. Standard pairwise graph neural networks restrict relational message passing to dyadic edges, whereas black-box sequence models violate fundamental cost-of-carry no-arbitrage identities and suffer catastrophic floating-point cancellation at short intraday horizons ($\Delta = 5$ minutes, $\Delta_{\mathrm{year}} = 1 / 11,250$ years).

# Core Hypothesis

We formulate a Regime-Conditioned Finance-Informed Hypergraph Neural Network (RC-FIHGNN) whose Phase 0 mathematical architecture couples three provable mechanisms:
1. Exact affine cost-of-carry basis decomposition under both continuous dividend yields and discrete cash-dividend schedules, with bounded log-linearization remainder.
2. Closed-form discrete minimum-variance hedging bias characterization establishing an exact $O(\Delta)$ asymptotic discrepancy relative to continuous-time projection, paired with multi-step variance-reduction bounds across $k \in \{1, 3, 12\}$ bars.
3. A symmetric normalized dynamic hypergraph Laplacian $\boldsymbol{\Delta}_n = \mathbf{I}_M - \mathbf{S}_n$ whose spectrum is strictly confined to $[0, 1]$, combined with $\operatorname{expm1}$-stabilized Ornstein-Uhlenbeck transition kernels and hard admissibility projection achieving zero bound-violation rate.

# Proposed Methodology (Phase 0 Mathematical Architecture)

Let $F_n > 0$ and $S_n > 0$ denote synchronized 5-minute closing levels of `VN30F1M` and `VN30INDEX` over continuous matching sessions ($225$ minutes/day across $250$ trading days/year). At bar $n$, node features across the $M$-node market universe $\mathcal{V}$ (comprising futures, spot index, and $30$ active constituent equities) are organized into a time-indexed weighted hypergraph $\mathcal{H}_n = (\mathcal{V}, \mathcal{E}_n, \mathbf{W}_n)$ with incidence matrix $\mathbf{H}_n \in \mathbb{R}^{M \times E_n}$.

Normalized hypergraph propagation uses $\mathbf{S}_n = \mathbf{D}_{v,n}^{-1/2} \mathbf{H}_n \mathbf{W}_n \mathbf{D}_{e,n}^{-1} \mathbf{H}_n^\top \mathbf{D}_{v,n}^{-1/2}$ and normalized Laplacian $\boldsymbol{\Delta}_n = \mathbf{I}_M - \mathbf{S}_n$, guaranteeing real eigenvalues in $[0, 1]$. Intraday basis mean-reversion transitions over step $\Delta$ evaluate $\operatorname{expm1}(-\kappa_n \Delta)$ rather than naive $1 - \exp(-\kappa_n \Delta)$ to preserve machine-precision accuracy down to dimensionless stiffness $x = 10^{-13}$.

# Expected Contributions

1. Rigorous Phase 0 data-alignment and mathematical foundations for intraday index futures hypergraph modeling on synchronized 5-minute `VN30F1M`, `VN30INDEX`, and 30-stock constituent order-flow panels.
2. Exact analytical and numerical verification of discrete hedging $O(\Delta)$ convergence, multi-horizon geometric decay ratios, spectral stability of $\boldsymbol{\Delta}_n$, and zero-violation admissibility projection.
