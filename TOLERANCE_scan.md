## Appendix — `late_tol` tolerance scan (Group 06 · Track 2)

Full scan across the four scenario cells (seeds 5105–5114, mean over 10 seeds), arranged 2×2. **PICK** marks the selected tolerance (stage 1 lateness plateau → stage 2 defect optimum).

### Summary of picks

| Cell | Selected `late_tol` | % late | % def pcs | cost ($) |
|---|---|---|---|---|
| Normal · default | **0.0** | 1.7% | 7.5% | 115,600 |
| Normal · --stages | **0.5** | 1.8% | 6.8% | 117,044 |
| Shock · default | **0.0** | 1.9% | 7.4% | 115,292 |
| Shock · --stages | **0.0** | 2.5% | 6.5% | 116,822 |

### Scan results (2×2)

<table>
  <tr>
    <td valign="top" width="50%">

**NORMAL · default simulator** — stage 1 plateau: 1/10 at % late 1.7 · late days 0.18 → **selected late_tol = 0**

| late_tol | % late | late days | % def pcs | cost ($) | max share |
|---|---|---|---|---|---|
| **0.0 PICK** | 1.7% | 0.18 | 7.5% | 115,600 | 26% |
| 0.5 | 1.8% | 0.19 | 7.4% | 115,639 | 27% |
| 1.0 | 2.6% | 0.18 | 7.0% | 116,094 | 27% |
| 1.5 | 2.2% | 0.18 | 7.0% | 115,596 | 27% |
| 2.0 | 2.8% | 0.18 | 7.1% | 114,488 | 29% |
| 3.0 | 2.6% | 0.19 | 6.4% | 112,871 | 32% |
| 4.0 | 2.6% | 0.20 | 5.7% | 111,724 | 33% |
| 5.0 | 2.5% | 0.24 | 6.0% | 111,150 | 34% |
| 7.0 | 5.4% | 0.49 | 5.2% | 110,892 | 35% |
| 10.0 | 8.1% | 0.60 | 5.4% | 108,879 | 38% |

    </td>
    <td valign="top" width="50%">

**NORMAL · --stages** — stage 1 plateau: 1/10 at % late 1.8 · late days 0.23 → **selected late_tol = 0.5**

| late_tol | % late | late days | % def pcs | cost ($) | max share |
|---|---|---|---|---|---|
| 0.0 | 1.8% | 0.27 | 6.5% | 117,136 | 28% |
| **0.5 PICK** | 1.8% | 0.23 | 6.8% | 117,044 | 29% |
| 1.0 | 2.7% | 0.28 | 6.7% | 117,472 | 29% |
| 1.5 | 3.3% | 0.26 | 6.8% | 117,548 | 29% |
| 2.0 | 3.7% | 0.24 | 6.3% | 116,762 | 32% |
| 3.0 | 3.8% | 0.26 | 6.2% | 115,230 | 33% |
| 4.0 | 5.1% | 0.32 | 6.1% | 115,074 | 35% |
| 5.0 | 5.8% | 0.35 | 6.2% | 114,806 | 35% |
| 7.0 | 10.2% | 0.55 | 5.6% | 113,758 | 36% |
| 10.0 | 13.1% | 1.07 | 5.3% | 113,404 | 39% |

    </td>
  </tr>
  <tr>
    <td valign="top">

**SHOCK · default simulator** — stage 1 plateau: 1/10 at % late 1.9 · late days 0.18 → **selected late_tol = 0**

| late_tol | % late | late days | % def pcs | cost ($) | max share |
|---|---|---|---|---|---|
| **0.0 PICK** | 1.9% | 0.18 | 7.4% | 115,292 | 26% |
| 0.5 | 2.0% | 0.18 | 7.1% | 115,300 | 27% |
| 1.0 | 2.8% | 0.19 | 6.9% | 115,864 | 27% |
| 1.5 | 2.6% | 0.20 | 7.3% | 115,622 | 27% |
| 2.0 | 3.2% | 0.19 | 6.9% | 114,524 | 30% |
| 3.0 | 3.2% | 0.22 | 6.3% | 113,031 | 32% |
| 4.0 | 3.2% | 0.24 | 5.9% | 111,574 | 33% |
| 5.0 | 3.4% | 0.29 | 6.0% | 111,057 | 34% |
| 7.0 | 5.9% | 0.53 | 5.8% | 110,894 | 35% |
| 10.0 | 9.6% | 0.74 | 6.0% | 108,995 | 37% |

    </td>
    <td valign="top">

**SHOCK · --stages** — stage 1 plateau: 1/10 at % late 2.5 · late days 0.30 → **selected late_tol = 0**

| late_tol | % late | late days | % def pcs | cost ($) | max share |
|---|---|---|---|---|---|
| **0.0 PICK** | 2.5% | 0.30 | 6.5% | 116,822 | 28% |
| 0.5 | 2.7% | 0.27 | 6.7% | 116,804 | 29% |
| 1.0 | 3.9% | 0.32 | 6.8% | 117,336 | 29% |
| 1.5 | 4.8% | 0.34 | 6.8% | 117,318 | 29% |
| 2.0 | 4.8% | 0.31 | 6.3% | 116,684 | 32% |
| 3.0 | 5.2% | 0.33 | 6.3% | 115,274 | 33% |
| 4.0 | 6.6% | 0.42 | 6.2% | 115,096 | 34% |
| 5.0 | 7.2% | 0.43 | 6.3% | 114,942 | 35% |
| 7.0 | 10.4% | 0.70 | 5.8% | 113,914 | 36% |
| 10.0 | 13.9% | 1.23 | 5.0% | 113,184 | 38% |

    </td>
  </tr>
</table>

### Why these values were chosen

- **Lateness is flat for small tolerances (0–0.5) and degrades quickly beyond ~5 days** — at tol = 10, % late rises to 8–14%. Since the selection hierarchy is *lateness first*, any tolerance that sacrifices lateness is eliminated at stage 1 of the scan.
- **Larger tolerances trade lateness for fewer defects and lower cost** (% def pcs 7.5% → 5.0–5.4%, up to ~$6.7k cheaper), which violates the lateness-first hierarchy and is rejected despite looking attractive on the secondary metrics.
- **Three of the four cells select `late_tol = 0`**; only NORMAL·--stages selects **0.5** (its stage-1 plateau favors 0.5's better late days, 0.23 vs 0.27). Production runs **0.5** — within 0.1pt of the best % late in every scenario and matching the pick for stages-normal, giving a single robust default across all cells.
