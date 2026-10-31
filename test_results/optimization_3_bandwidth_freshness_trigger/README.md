| Test | Metric | Before (RTT slow mode, 929477a) | After (freshness trigger) |
|---|---|---|---|
| **Bandwidth (300 clients, 2 Mbit)** | **Fresh Final Ratio** | **0.00%** | **87.24%** |
| | **Completeness** | **98.93%** | **100%** |
| | **P50 / P99** | **1.14 s / 1.72 s** | **82 ms / 1.27 s** |
| | Fresh Caption Ratio | 0.90% | 78.92% |
| | Coverage | 85.77% | 37.44% |
| Burst 20 / 100 | Coverage | 100% / 100% | 100% / 100% |
| | P99 | 5.5 / 27.5 ms | 3.1 / 39.3 ms |
| T1 | Coverage / completeness | 100% / 100% | 100% / 100% |
| | P99 | 4.9 ms | 4.7 ms |
| T2 | Coverage / completeness | 100% / 100% | 100% / 100% |
| | P95 / P99 | 11.2 / 18.1 ms | 14.9 / 20.0 ms |
| T3 | Completeness / coverage | 99.21% / 94.91% | 99.21% / 94.91% |
| | Slow-client P50 / overall P99 | 3.59 s / 6.60 s | 3.59 s / 6.59 s |
| | Normal-client P95 | 11.2 ms | 8.5 ms |
| T4 | Completeness / recovery P95 | 100% / 2.2 ms | 100% / 2.4 ms |
| | P95 | 5.3 ms | 5.3 ms |
| T5 | Coverage / completeness | 99.36% / 100% | 99.15% / 100% |
| | P95 / P99 | 642 / 813 ms | 522 / 749 ms |
| | Fresh Final Ratio | 89.71% | 92.20% (per-run ranges overlap) |

```bash
# Bandwidth
sudo ./network_profiles/bandwidth_2mbit.sh lo
python run_demo.py --clients 300 --duration 40 --runs 3 --output-stem bw300
sudo ./network_profiles/reset.sh lo

# T1-T4
python run_demo.py --clients 20 --duration 20 --runs 3 --output-stem t1
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t2
python run_demo.py --clients 100 --duration 60 --runs 3 --slow-percent 10 --slow-ms 500 --output-stem t3
python run_demo.py --clients 100 --duration 60 --runs 3 --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 --output-stem t4

# T5
sudo ./network_profiles/delay_loss.sh lo
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t5
sudo ./network_profiles/reset.sh lo

# Burst (N clients, D seconds, S segments: 20/20/22 and 100/40/49), once per run
python solution_server.py --port 8765 &
python load_clients.py --uri ws://127.0.0.1:8765 --clients N --duration D --output burstN.csv --seed 3103 --history-seconds 30 &
sleep 1
python caption_source.py --uri ws://127.0.0.1:8765 --segments S --revision-delay 0 --segment-gap 0.75 --quiet
wait %2; kill %1
python analyse_results.py burstN.csv --expected-finals S --expected-updates $((S * 3)) --json-output burstN.json
```
