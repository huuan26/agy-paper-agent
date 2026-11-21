# Experimental Log (Phase 0 Gate G0 Data Audit & Mathematical Verification)

## 1. Gate G0 Intraday Data Synchronization Audit
- Synchronized 5-minute (`5m`) intraday panel via `ohlcv-dev` covering 10 channels (`o, h, l, c, v, bu, sd, fb, fs, fn`) with field coverage ratio `1.0` (`100%`) across all series:
  - `VN30F1M`: `74,256` bars across `1,516` trading days (`48.98` average bars/day, `2020-01-02` to `2026-01-30`, contract multiplier `100,000` VND/point).
  - `VN30INDEX`: `50,761` bars across `1,059` trading days (`47.93` average bars/day, `2021-11-04` to `2026-01-30`).
  - Constituent equities: `30` active recent-basket stocks (`50` in historical union) with `100%` (`1.0`) 10-channel coverage from `2022_Q1` through `2026_JAN`.
- Continuous matching grid: `225` synchronized minutes/day, bar step $\Delta = 5$ minutes, `250` trading days/year, annualized step $\Delta_{\mathrm{year}} = 1 / 11,250$ years.

## 2. Raw Numeric Verification Results (`verify_phase0_math.py`)
- **Proposition 1 (Exact Cost-of-Carry Affine Factorization)**: Continuous-yield residual = `0.0`, discrete-dividend residual = `0.0`.
- **Proposition 2 (Discrete vs. Continuous Hedging Discrepancy)**:
  - 12-level dyadic refinement errors ($m = 0, \dots, 11$): `[0.03555555555555555, 0.018713450292397654, 0.009609609609609607, 0.00487062404870624, 0.002452107279693486, 0.0012302960399846212, 0.0006162141344117079, 0.0003083742892936301, 0.00015425403711737763, 7.714375256141365e-05, 3.8576061143056904e-05, 1.9289076957389223e-05]`.
  - Final empirical convergence order: `0.999922` (theoretical order `1.00`).
- **Basis Decomposition Remainder Bound (`10,000` trials)**: Maximum empirical remainder = `0.640735` bps.
- **Lemma 3 Multi-Horizon Variance Ratio (`400,000` Monte Carlo paths)**:
  - $p = 0.1$: $k = 1 \to \text{MC } 0.90107, \text{ Theory } 0.90000, \text{ AbsErr } 0.00107$; $k = 3 \to \text{MC } 0.96420, \text{ Theory } 0.96300, \text{ AbsErr } 0.00120$; $k = 12 \to \text{MC } 0.99077, \text{ Theory } 0.99074, \text{ AbsErr } 0.00003$.
  - $p = 0.3$: $k = 1 \to \text{MC } 0.70086, \text{ Theory } 0.70000, \text{ AbsErr } 0.00086$; $k = 3 \to \text{MC } 0.86012, \text{ Theory } 0.86100, \text{ AbsErr } 0.00088$; $k = 12 \to \text{MC } 0.96464, \text{ Theory } 0.96429, \text{ AbsErr } 0.00036$.
  - $p = 0.6$: $k = 1 \to \text{MC } 0.40019, \text{ Theory } 0.40000, \text{ AbsErr } 0.00019$; $k = 3 \to \text{MC } 0.60927, \text{ Theory } 0.60800, \text{ AbsErr } 0.00127$; $k = 12 \to \text{MC } 0.87739, \text{ Theory } 0.87527, \text{ AbsErr } 0.00211$.
- **Ornstein-Uhlenbeck `expm1` Conditioning ($x = 10^{-13}$)**: `expm1` absolute error = `1.1102230246251565e-16` vs. naive `1 - exp(-x)` error = `0.00024416632494650425`.
- **Hypergraph Spectral & Admissibility Verification**:
  - Propagation symmetry error $\|\mathbf{S}_n - \mathbf{S}_n^\top\|_F = 2.7755575615628914 \times 10^{-17}$.
  - Normalized hypergraph Laplacian $\boldsymbol{\Delta}_n$ eigenvalue interval: `[0.0, 1.0]`.
  - Hard admissibility projection (`10,000` fuzz trials): bound-violation rate (`BVR`) = `0.0` (`0.00%`).
  - Closed-form Gaussian CRPS vs. numerical quadrature error: `6.505213034913027e-19`.
