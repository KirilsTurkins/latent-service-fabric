# Issue 106: primary external full04

This completed external campaign is retained independently of the failed matrix04 and any later corrected matrix. This extraction checked aggregate population, actual pair associations and stored paired arithmetic; it did not rerun semantic replay or any workload.

## Identity and accounting

Control `172c5a3f2ea9c8b233a780bafdcb4c2d453f939b`; candidate/shared harness `9e50564cb2fbe78e1c136e634fcca6747c6779f8`.
Aggregate `sha256:b2cc3e2ac920b7a7ee52d53a81958a25d5ebcadfdebfe0b72dd696efcade2501` (573,109 bytes); suite `sha256:92f17fe3c2afd162828b7dc75f628e7740772769743333a30bb2b6e18917cec2` (383,515 bytes). Exact source trees, clean source receipts, binaries, build settings, environment and every pair are retained in the [combined analysis](analysis.json).

6,160 total Invokes: 560 warmup and 5,600 measured, across seven process pairs. Each arm has 280 warmup and 2,800 measured calls. The 42 validated owners include 14 seed servers, 14 measured servers and 14 clients.
Collection elapsed 17.651233992 s; suite elapsed 17.742795272 s. Actual CPU clock: 100 Hz.

## Paired measurements

Latency rows use microseconds; other units are named. Medians summarize seven process quantiles/values. Paired delta is candidate minus control; it is not a difference of arm medians.

| Metric | Control median | Candidate median | Median paired delta | Median paired % | Lower/equal/higher | Available pairs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| successful_response_latency p50 | 525.7915 | 513.0115 | -13.0635 | -2.50432772215161117788807159 | 5/0/2 | 7/7 |
| successful_response_latency p95 | 986.765 | 905.782 | -81.542 | -8.26356832680526771825105268 | 5/0/2 | 7/7 |
| successful_response_latency p99 | 1273.965 | 1299.335 | 28.086 | 2.154217621540028594044339177 | 3/0/4 | 7/7 |
| all_offered_elapsed p50 | 589.0105 | 579.4005 | -8.0655 | -1.372930518532136327889614037 | 5/0/2 | 7/7 |
| all_offered_elapsed p95 | 1076.263 | 1006.613 | -47.889 | -4.449562978565647987527212215 | 6/0/1 | 7/7 |
| all_offered_elapsed p99 | 1394.547 | 1353.265 | -59.569 | -4.097522254039638707618272628 | 4/0/3 | 7/7 |
| Successful responses/s | 1380.779141 | 1406.851016 | 16.276728 | 1.178807494746185479926800256 | 3/0/4 | 7/7 |
| Attempts/s | 1380.779141 | 1406.851016 | 16.276728 | 1.178807494746185479926800256 | 3/0/4 | 7/7 |
| Server batch CPU ticks | 25 | 24 | -1 | -4 | 4/2/1 | 7/7 |
| Client batch CPU ticks | 13 | 12 | -1 | -7.142857142857142857142857145 | 4/1/2 | 7/7 |
| Server sampled maximum RSS bytes | 25657344 | 25796608 | -53248 | -0.208969619032309918019610995 | 4/0/3 | 7/7 |
| Client sampled maximum RSS bytes | 4587520 | 4587520 | 0 | 0 | 3/2/2 | 7/7 |

## Offered outcomes and total batch CPU

- control: server CPU 1.82 s; client CPU 0.9 s.
  warmup: 280 offers, outcomes `{"success": 280}`; 280 useful/on-time successes, 0 budget misses.
  measured: 2800 offers, outcomes `{"success": 2800}`; 2800 useful/on-time successes, 0 budget misses.
- candidate: server CPU 1.7 s; client CPU 0.86 s.
  warmup: 280 offers, outcomes `{"success": 280}`; 280 useful/on-time successes, 0 budget misses.
  measured: 2800 offers, outcomes `{"success": 2800}`; 2800 useful/on-time successes, 0 budget misses.

## All seven paired differences

Each row below is an actual process pair; all values are candidate minus control. Full unrounded baseline/candidate values and percentages are in [analysis.json](analysis.json).

| Pair | Order | successful_response_latency p50 | successful_response_latency p95 | successful_response_latency p99 | all_offered_elapsed p50 | all_offered_elapsed p95 | all_offered_elapsed p99 | Successful responses/s | Attempts/s | Server batch CPU ticks | Client batch CPU ticks | Server sampled maximum RSS bytes | Client sampled maximum RSS bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | baseline-first | -33.606 | -88.513 | 28.086 | -42.887 | -105.236 | -65.889 | 107.899185 | 107.899185 | -4 | -1 | -131072 | 131072 |
| 2 | candidate-first | -83.342 | -234.533 | -338.189 | -106.5555 | -203.431 | -383.628 | 271.010186 | 271.010186 | -4 | -3 | 106496 | -131072 |
| 3 | baseline-first | 2.405 | 8.591 | 55.941 | 0.1365 | -33.374 | 69.705 | -4.245002 | -4.245002 | 0 | 1 | -258048 | 0 |
| 4 | candidate-first | -35.753 | -190.863 | -129.424 | -36.018 | -240.138 | -155.102 | 99.312955 | 99.312955 | -4 | -1 | 655360 | 262144 |
| 5 | baseline-first | -13.0635 | -81.542 | -17.177 | -8.0655 | -47.889 | -59.569 | 16.276728 | 16.276728 | -1 | 1 | -53248 | -262144 |
| 6 | candidate-first | -0.508 | -4.587 | 133.252 | -4.6235 | -8.106 | 31.333 | -20.187742 | -20.187742 | 0 | -1 | 368640 | -131072 |
| 7 | baseline-first | 12.142 | 40.763 | 63.141 | 11.5745 | 86.419 | 33.345 | -55.379727 | -55.379727 | 1 | 0 | -225280 | 0 |

## Execution-order strata

These are the predeclared alternating order subsets (four control-first, three candidate-first), not new independent campaigns.

| Metric | Order | Pairs | Control median | Candidate median | Median paired delta | Lower/equal/higher |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| successful_response_latency p50 | baseline-first | 4 | 523.71425 | 520.604 | -5.32925 | 2/0/2 |
| successful_response_latency p50 | candidate-first | 3 | 552.8515 | 512.927 | -35.753 | 3/0/0 |
| successful_response_latency p95 | baseline-first | 4 | 953.034 | 916.7485 | -36.4755 | 2/0/2 |
| successful_response_latency p95 | candidate-first | 3 | 1051.03 | 869.175 | -190.863 | 3/0/0 |
| successful_response_latency p99 | baseline-first | 4 | 1282.3015 | 1308.0555 | 42.0135 | 1/0/3 |
| successful_response_latency p99 | candidate-first | 3 | 1273.965 | 1144.541 | -129.424 | 2/0/1 |
| all_offered_elapsed p50 | baseline-first | 4 | 588.23825 | 584.27375 | -3.9645 | 2/0/2 |
| all_offered_elapsed p50 | candidate-first | 3 | 618.206 | 570.2115 | -36.018 | 3/0/0 |
| all_offered_elapsed p95 | baseline-first | 4 | 1058.125 | 1017.2065 | -40.6315 | 3/0/1 |
| all_offered_elapsed p95 | candidate-first | 3 | 1111.045 | 942.283 | -203.431 | 3/0/0 |
| all_offered_elapsed p99 | baseline-first | 4 | 1383.655 | 1385.563 | -13.112 | 2/0/2 |
| all_offered_elapsed p99 | candidate-first | 3 | 1394.547 | 1239.445 | -155.102 | 2/0/1 |
| Successful responses/s | baseline-first | 4 | 1389.4882745 | 1395.5041375 | 6.015863 | 2/0/2 |
| Successful responses/s | candidate-first | 3 | 1307.538061 | 1406.98965 | 99.312955 | 1/0/2 |
| Attempts/s | baseline-first | 4 | 1389.4882745 | 1395.5041375 | 6.015863 | 2/0/2 |
| Attempts/s | candidate-first | 3 | 1307.538061 | 1406.98965 | 99.312955 | 1/0/2 |
| Server batch CPU ticks | baseline-first | 4 | 25 | 25 | -0.5 | 2/1/1 |
| Server batch CPU ticks | candidate-first | 3 | 27 | 24 | -4 | 2/1/0 |
| Client batch CPU ticks | baseline-first | 4 | 12 | 13 | 0.5 | 1/1/2 |
| Client batch CPU ticks | candidate-first | 3 | 13 | 12 | -1 | 3/0/0 |
| Server sampled maximum RSS bytes | baseline-first | 4 | 25655296 | 25427968 | -178176 | 4/0/0 |
| Server sampled maximum RSS bytes | candidate-first | 3 | 25690112 | 26058752 | 368640 | 0/0/3 |
| Client sampled maximum RSS bytes | baseline-first | 4 | 4587520 | 4587520 | 0 | 1/2/1 |
| Client sampled maximum RSS bytes | candidate-first | 3 | 4587520 | 4456448 | -131072 | 2/0/1 |

## Scope

- Whole collector/archive semantic replay is not repeated by this analysis; original aggregate is complete with both flags true.
- No matrix partial result, later campaign or historical median is pooled or subtracted.
- Seven process pairs and their 4/3 order strata are descriptive, not equivalence or a universal SLO.
- Successful response quantiles condition on success; all-offered outcomes and on-time denominators remain retained.
- Server/client CPU includes batch warmup and observation; RSS is a sampled maximum, not an instantaneous peak.
- The source-only per-offer deadline correction affects the separate matrix collector; this external04 identity is never relabelled.
