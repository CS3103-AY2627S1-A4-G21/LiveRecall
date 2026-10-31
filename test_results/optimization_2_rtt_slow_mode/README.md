| Test | Metric | Before (ping window, 163916e) | After (RTT slow mode) |
|---|---|---|---|
| Burst 20 / 100 | Coverage | 100% / 100% | 100% / 100% |
| | P99 | 10.3 / 33.9 ms | 13.6 / 47.4 ms |
| T1 | Coverage / completeness | 100% / 100% | 100% / 100% |
| | P99 | 7.6 ms | 10.0 ms |
| T2 | Coverage / completeness | 100% / 100% | 100% / 100% |
| | P95 / P99 | 24.8 / 32.5 ms | 18.8 / 27.9 ms |
| **T3** | **Completeness** | **98.76%** | **99.21%** |
| | **Slow-client P50 / overall P99** | **8.14 s / 8.85 s** | **3.62 s / 6.60 s** |
| | Overall P95 | 2.28 s | 25.9 ms |
| | Fresh Final Ratio | 90.00% | 91.97% |
| | Coverage | 95.18% | 94.91% |
| | Normal-client P95 | 18.2 ms | 16.4 ms |
| T4 | Completeness / recovery P95 | 100% / 5.3 ms | 100% / 8.1 ms |
| | P95 | 16.0 ms | 19.7 ms |
| T5 | Coverage | 99.12% | 99.24% |
| | Completeness | 100% | 100% (one run 99.96%) |
| | P99 / Fresh Final Ratio | 992 ms / 86.3% | 1,069 ms / 87.6% (per-run ranges overlap) |
