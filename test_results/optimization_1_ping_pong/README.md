| Test | Metric | Before (burst fix, 283ef70) | After (ping window) |
|---|---|---|---|
| Burst 20 / 100 | Coverage | 100% / 100% | 100% / 100% |
| | P99 | 4.0 / 15.6 ms | 4.8 / 18.1 ms |
| T1 | Coverage / completeness | 100% / 100% | 100% / 100% |
| | P99 | 1.6 ms | 2.5 ms |
| T2 | Coverage / completeness | 100% / 100% | 100% / 100% |
| | P95 / P99 | 4.5 / 7.8 ms | 9.8 / 11.7 ms |
| **T3** | **Completeness** | **95.13%** | **98.68%** |
| | **Slow-client P50 / overall P99** | **14.71 s / 24.02 s** | **8.08 s / 8.82 s** |
| | Normal-client P95 | 7.5 ms | 10.1 ms |
| T4 | Completeness / recovery P95 | 100% / 3.5 ms | 100% / 3.8 ms |
| | P95 | 6.6 ms | 14.5 ms |
| **T5** | **Coverage** | **99.99%** | **99.20%** |
| | Completeness | 100% | 100% |
| | P99 / Fresh Final Ratio | 940 ms / 89.4% | 994 ms / 86.5% (per-run ranges overlap) |
