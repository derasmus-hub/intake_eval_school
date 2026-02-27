# Full Loop v4 Trajectory Test Report

**Date**: 2026-02-27T19:18:43.333976+00:00
**Student**: 5


## Patch Results
| Patch | Description | Status |
|-------|-------------|--------|
| patch1_windowed_avg | Windowed avg (last 8) | **PASS** |
| patch2_confidence | Confidence 0.6 | **PASS** |
| patch3_cold_start | Cold start 2pts | **PASS** |
| patch4_auto_progress | Auto-progress | **PASS** |
| patch5_trajectory | Trajectory-aware reassessment | **PASS** |

## PATCH 5 Detail

- Before: A1, After: A2

- Confidence: 0.8, Trajectory: improving

- Natural: True, DB Changed: True


## DNA Evolution
| Cycle | Recent Avg | Lifetime Avg | Recommendation |
|---|---|---|---|
| 1 | 20.0 | 20.0 | decrease_difficulty |
| 2 | 26.5 | 26.5 | decrease_difficulty |
| 3 | 26.5 | 26.5 | decrease_difficulty |
| 4 | 31.0 | 31.0 | decrease_difficulty |
| 5 | 38.25 | 38.25 | decrease_difficulty |
| 6 | 38.25 | 38.25 | decrease_difficulty |
| 7 | 42.6 | 42.6 | decrease_difficulty |
| 8 | 48.83 | 48.83 | decrease_difficulty |
| 9 | 53.29 | 53.29 | decrease_difficulty |
| 10 | 57.0 | 57.0 | decrease_difficulty |
| 11 | 59.5 | 55.11 | decrease_difficulty |
| 12 | 63.75 | 56.3 | decrease_difficulty |
| 13 | 67.12 | 57.27 | decrease_difficulty |
| 14 | 69.62 | 59.17 | decrease_difficulty |
| 15 | 72.12 | 60.77 | maintain |

## Full Cycle Data
| Cycle | Target | Actual | Level | Plan v | DNA Rec | Recent | Lifetime | Skip | Reassessment |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 15% | 20% | A1 | 1 | decrease_difficulty | 20.0 | 20.0 |  |  |
| 2 | 25% | 33% | A1 | 2 | decrease_difficulty | 26.5 | 26.5 |  |  |
| 3 | 32% | 40% | A1 | 3 | decrease_difficulty | 26.5 | 26.5 | YES |  |
| 4 | 42% | 40% | A1 | 4 | decrease_difficulty | 31.0 | 31.0 |  |  |
| 5 | 52% | 60% | A1 | 5 | decrease_difficulty | 38.25 | 38.25 |  |  |
| 6 | 60% | 67% | A1 | 6 | decrease_difficulty | 38.25 | 38.25 | YES |  |
| 7 | 67% | 60% | A1 | 7 | decrease_difficulty | 42.6 | 42.6 |  |  |
| 8 | 73% | 80% | A1 | 8 | decrease_difficulty | 48.83 | 48.83 |  |  |
| 9 | 80% | 80% | A1 | 9 | decrease_difficulty | 53.29 | 53.29 |  |  |
| 10 | 85% | 83% | A2 | 10 | decrease_difficulty | 57.0 | 57.0 |  | ->A2 |
| 11 | 50% | 40% | A2 | 11 | decrease_difficulty | 59.5 | 55.11 |  |  |
| 12 | 63% | 67% | A2 | 12 | decrease_difficulty | 63.75 | 56.3 |  |  |
| 13 | 74% | 67% | A2 | 13 | decrease_difficulty | 67.12 | 57.27 |  |  |
| 14 | 83% | 80% | A2 | 14 | decrease_difficulty | 69.62 | 59.17 |  |  |
| 15 | 90% | 80% | A2 | 15 | maintain | 72.12 | 60.77 |  |  |