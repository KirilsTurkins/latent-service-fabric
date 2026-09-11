# Issue 106 descriptive extraction

Input full-population and aggregate arithmetic checks passed. This helper did not perform semantic replay.

## External warm D0

| Metric (original units) | Control median | Candidate median | Median paired delta | Lower/equal/higher | Available pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| all_offered_elapsed_nanos_median | 589010.5 | 579400.5 | -8065.5 | 5/0/2 | 7/7 |
| all_offered_elapsed_nanos_p95 | 1076263 | 1006613 | -47889 | 6/0/1 | 7/7 |
| all_offered_elapsed_nanos_p99 | 1394547 | 1353265 | -59569 | 4/0/3 | 7/7 |
| attempts_per_second | 1380.779141 | 1406.851016 | 16.276728 | 3/0/4 | 7/7 |
| budget_misses | 0 | 0 | 0 | 0/7/0 | 7/7 |
| budget_successes | 400 | 400 | 0 | 0/7/0 | 7/7 |
| client.cpu_seconds | 0.13 | 0.12 | -0.01 | 4/1/2 | 7/7 |
| client.cpu_system_ticks | 7 | 8 | 1 | 3/0/4 | 7/7 |
| client.cpu_ticks | 13 | 12 | -1 | 4/1/2 | 7/7 |
| client.cpu_user_ticks | 5 | 4 | -1 | 4/2/1 | 7/7 |
| client.last_live_rss_bytes | 4587520 | 4587520 | 0 | 3/2/2 | 7/7 |
| client.read_bytes | 0 | 0 | 0 | 0/7/0 | 7/7 |
| client.sampled_peak_rss_bytes | 4587520 | 4587520 | 0 | 3/2/2 | 7/7 |
| client.write_bytes | 585728 | 585728 | 0 | 0/7/0 | 7/7 |
| server.cpu_seconds | 0.25 | 0.24 | -0.01 | 4/2/1 | 7/7 |
| server.cpu_system_ticks | 6 | 7 | 1 | 2/1/4 | 7/7 |
| server.cpu_ticks | 25 | 24 | -1 | 4/2/1 | 7/7 |
| server.cpu_user_ticks | 19 | 17 | -2 | 6/0/1 | 7/7 |
| server.last_live_rss_bytes | 25657344 | 25796608 | -53248 | 4/0/3 | 7/7 |
| server.read_bytes | 0 | 0 | 0 | 0/7/0 | 7/7 |
| server.sampled_peak_rss_bytes | 25657344 | 25796608 | -53248 | 4/0/3 | 7/7 |
| server.write_bytes | 0 | 0 | 0 | 0/7/0 | 7/7 |
| successes_per_second | 1380.779141 | 1406.851016 | 16.276728 | 3/0/4 | 7/7 |
| successful_response_latency_nanos_median | 525791.5 | 513011.5 | -13063.5 | 5/0/2 | 7/7 |
| successful_response_latency_nanos_p95 | 986765 | 905782 | -81542 | 5/0/2 | 7/7 |
| successful_response_latency_nanos_p99 | 1273965 | 1299335 | 28086 | 3/0/4 | 7/7 |

## Five profile medians

| Metric (original units) | O | D0 | P0 | D1 | P1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| fresh_engine_first_echo.latency_nanos | 34827748 | 36030747 | 39429435 | 35192727 | 37899789 |
| derived.preparation.component_new.median_nanos | 32188655.5 | 33250055 | 39503623.5 | 33727406 | 36748370.5 |
| preparation.component_new.total_cpu_ticks | 21 | 22 | 26 | 22 | 24 |
| process.population_and_controls.cpu_seconds | 2.89 | 2.82 | 2.85 | 2.84 | 2.82 |
| derived.memory.vm_size_bytes.maximum | 863084544 | 863141888 | 1409159168 | 863141888 | 1409159168 |
| derived.memory.vm_peak_bytes.maximum | 18319794176 | 18319851520 | 1409159168 | 18319851520 | 1474879488 |
| derived.memory.rss_bytes.maximum | 33615872 | 33480704 | 34304000 | 33587200 | 34447360 |
| derived.memory.vm_hwm_bytes.maximum | 36634624 | 36667392 | 37576704 | 36794368 | 37744640 |
| raw.before-shutdown.resident.compiled_image_bytes | 743312 | 743312 | 829360 | 743312 | 829360 |

## default-preservation

| Metric (original units) | Baseline median | Candidate median | Median paired delta | Lower/equal/higher | Available pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| fresh_engine_first_echo.latency_nanos | 34827748 | 36030747 | 2079252 | 3/0/4 | 7/7 |
| derived.preparation.component_new.median_nanos | 32188655.5 | 33250055 | 1033886.5 | 2/0/5 | 7/7 |
| preparation.component_new.total_cpu_ticks | 21 | 22 | 1 | 2/1/4 | 7/7 |
| process.population_and_controls.cpu_seconds | 2.89 | 2.82 | -0.1 | 5/0/2 | 7/7 |
| derived.memory.vm_size_bytes.maximum | 863084544 | 863141888 | 57344 | 0/0/7 | 7/7 |
| derived.memory.vm_peak_bytes.maximum | 18319794176 | 18319851520 | 57344 | 0/0/7 | 7/7 |
| derived.memory.rss_bytes.maximum | 33615872 | 33480704 | -278528 | 5/0/2 | 7/7 |
| derived.memory.vm_hwm_bytes.maximum | 36634624 | 36667392 | -57344 | 4/0/3 | 7/7 |
| raw.before-shutdown.resident.compiled_image_bytes | 743312 | 743312 | 0 | 0/7/0 | 7/7 |
| phase.echo.successful.median_nanos | 599843.5 | 609138 | 5893.5 | 1/0/6 | 7/7 |
| phase.echo.successful.p95_nanos | 1049487 | 1042597 | -21231 | 5/0/2 | 7/7 |
| phase.echo.successful.p99_nanos | 1361795 | 1351423 | 47189 | 3/0/4 | 7/7 |
| phase.echo.all_offered.p99_nanos | 1425131 | 1579220 | 86640 | 2/0/5 | 7/7 |
| phase.echo.backend_setup_micros.median | 49 | 51 | 3 | 1/1/5 | 7/7 |
| phase.echo.guest_call_micros.median | 52 | 53 | 1 | 1/1/5 | 7/7 |
| phase.echo.activation_resource_reclamation_micros.median | 26 | 27 | 1 | 2/1/4 | 7/7 |
| phase.echo.throughput_rps | 660.5447260357804098389715645 | 660.3413722218932896761841915 | 1.3366071400222876769396313 | 3/0/4 | 7/7 |
| phase.echo.process_cpu_ticks | 67 | 68 | 0 | 1/3/3 | 7/7 |
| phase.compute.successful.median_nanos | 1230044 | 1204083.5 | -69431.5 | 5/0/2 | 7/7 |
| phase.compute.successful.p95_nanos | 2045217 | 1977624 | -40374 | 5/0/2 | 7/7 |
| phase.compute.successful.p99_nanos | 2423798 | 2361645 | -62153 | 4/0/3 | 7/7 |
| phase.compute.all_offered.p99_nanos | 2468666 | 2442229 | -28344 | 4/0/3 | 7/7 |
| phase.compute.backend_setup_micros.median | 36.5 | 37 | 1 | 3/0/4 | 7/7 |
| phase.compute.guest_call_micros.median | 669 | 660 | 0 | 3/1/3 | 7/7 |
| phase.compute.activation_resource_reclamation_micros.median | 30 | 28 | -2 | 4/1/2 | 7/7 |
| phase.compute.throughput_rps | 447.3773462490846982795779102 | 452.9522673274173921844353124 | 11.9964045231696309080044206 | 2/0/5 | 7/7 |
| phase.compute.process_cpu_ticks | 33 | 32 | 0 | 3/2/2 | 7/7 |
| phase.memory.successful.median_nanos | 11497278 | 11193933.5 | -403339 | 6/0/1 | 7/7 |
| phase.memory.successful.p95_nanos | 14055028 | 13182190 | -694639 | 7/0/0 | 7/7 |
| phase.memory.successful.p99_nanos | 15660317 | 14570340 | -853610 | 4/0/3 | 7/7 |
| phase.memory.all_offered.p99_nanos | 15721428 | 14764495 | -720534 | 4/0/3 | 7/7 |
| phase.memory.backend_setup_micros.median | 62.5 | 65 | 2 | 3/0/4 | 7/7 |
| phase.memory.guest_call_micros.median | 10563.5 | 10097.5 | -557.5 | 6/0/1 | 7/7 |
| phase.memory.activation_resource_reclamation_micros.median | 208.5 | 208 | -0.5 | 5/0/2 | 7/7 |
| phase.memory.throughput_rps | 76.19558383444589283254001745 | 79.5798803042999337039912155 | 3.55170268550022437272406997 | 2/0/5 | 7/7 |
| phase.memory.process_cpu_ticks | 99 | 95 | -5 | 5/0/2 | 7/7 |
| phase.concurrent-echo.successful.median_nanos | 1136593 | 1112788.5 | -19260 | 5/0/2 | 7/7 |
| phase.concurrent-echo.successful.p95_nanos | 1880141 | 1968502 | 137715 | 3/0/4 | 7/7 |
| phase.concurrent-echo.successful.p99_nanos | 2171102 | 2299686 | 128584 | 3/0/4 | 7/7 |
| phase.concurrent-echo.all_offered.p99_nanos | 2337521 | 2444128 | 111433 | 3/0/4 | 7/7 |
| phase.concurrent-echo.backend_setup_micros.median | 65 | 67 | -2 | 5/0/2 | 7/7 |
| phase.concurrent-echo.guest_call_micros.median | 65 | 66.5 | 4 | 3/0/4 | 7/7 |
| phase.concurrent-echo.activation_resource_reclamation_micros.median | 37 | 35 | 0.5 | 3/0/4 | 7/7 |
| phase.concurrent-echo.throughput_rps | 961.8521617597277669826571445 | 935.4740341093565491678392065 | -6.4452520741511106980528086 | 4/0/3 | 7/7 |
| phase.concurrent-echo.process_cpu_ticks | 20 | 20 | 0 | 2/3/2 | 7/7 |

## pooling-speed

| Metric (original units) | Baseline median | Candidate median | Median paired delta | Lower/equal/higher | Available pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| fresh_engine_first_echo.latency_nanos | 36030747 | 39429435 | 3398688 | 1/0/6 | 7/7 |
| derived.preparation.component_new.median_nanos | 33250055 | 39503623.5 | 7015017.5 | 0/0/7 | 7/7 |
| preparation.component_new.total_cpu_ticks | 22 | 26 | 5 | 0/0/7 | 7/7 |
| process.population_and_controls.cpu_seconds | 2.82 | 2.85 | -0.05 | 4/0/3 | 7/7 |
| derived.memory.vm_size_bytes.maximum | 863141888 | 1409159168 | 546017280 | 0/0/7 | 7/7 |
| derived.memory.vm_peak_bytes.maximum | 18319851520 | 1409159168 | -16910692352 | 7/0/0 | 7/7 |
| derived.memory.rss_bytes.maximum | 33480704 | 34304000 | 765952 | 0/0/7 | 7/7 |
| derived.memory.vm_hwm_bytes.maximum | 36667392 | 37576704 | 884736 | 0/0/7 | 7/7 |
| raw.before-shutdown.resident.compiled_image_bytes | 743312 | 829360 | 86048 | 0/0/7 | 7/7 |
| phase.echo.successful.median_nanos | 609138 | 571103 | -53258.5 | 6/0/1 | 7/7 |
| phase.echo.successful.p95_nanos | 1042597 | 977870 | -64727 | 6/0/1 | 7/7 |
| phase.echo.successful.p99_nanos | 1351423 | 1243240 | -141500 | 6/0/1 | 7/7 |
| phase.echo.all_offered.p99_nanos | 1579220 | 1349941 | -103661 | 6/0/1 | 7/7 |
| phase.echo.backend_setup_micros.median | 51 | 33 | -18 | 7/0/0 | 7/7 |
| phase.echo.guest_call_micros.median | 53 | 46 | -7 | 6/0/1 | 7/7 |
| phase.echo.activation_resource_reclamation_micros.median | 27 | 25 | -2 | 6/0/1 | 7/7 |
| phase.echo.throughput_rps | 660.3413722218932896761841915 | 698.346583281291236547367858 | 38.0052110593979468711836664 | 1/0/6 | 7/7 |
| phase.echo.process_cpu_ticks | 68 | 64 | -4 | 5/1/1 | 7/7 |
| phase.compute.successful.median_nanos | 1204083.5 | 1071053 | -176653 | 6/0/1 | 7/7 |
| phase.compute.successful.p95_nanos | 1977624 | 1864512 | -230485 | 6/0/1 | 7/7 |
| phase.compute.successful.p99_nanos | 2361645 | 2162313 | -283317 | 5/0/2 | 7/7 |
| phase.compute.all_offered.p99_nanos | 2442229 | 2214942 | -273125 | 5/0/2 | 7/7 |
| phase.compute.backend_setup_micros.median | 37 | 20 | -16 | 7/0/0 | 7/7 |
| phase.compute.guest_call_micros.median | 660 | 518.5 | -186 | 7/0/0 | 7/7 |
| phase.compute.activation_resource_reclamation_micros.median | 28 | 17 | -12 | 7/0/0 | 7/7 |
| phase.compute.throughput_rps | 452.9522673274173921844353124 | 470.114966064034983899021509 | 52.2796306005870840022497923 | 2/0/5 | 7/7 |
| phase.compute.process_cpu_ticks | 32 | 32 | -2 | 5/0/2 | 7/7 |
| phase.memory.successful.median_nanos | 11193933.5 | 10516593.5 | -331079.5 | 6/0/1 | 7/7 |
| phase.memory.successful.p95_nanos | 13182190 | 13045833 | 277211 | 3/0/4 | 7/7 |
| phase.memory.successful.p99_nanos | 14570340 | 15799842 | -193996 | 4/0/3 | 7/7 |
| phase.memory.all_offered.p99_nanos | 14764495 | 15929275 | -207922 | 4/0/3 | 7/7 |
| phase.memory.backend_setup_micros.median | 65 | 40 | -18 | 7/0/0 | 7/7 |
| phase.memory.guest_call_micros.median | 10097.5 | 9451 | -273 | 6/0/1 | 7/7 |
| phase.memory.activation_resource_reclamation_micros.median | 208 | 214.5 | -10.5 | 4/0/3 | 7/7 |
| phase.memory.throughput_rps | 79.5798803042999337039912155 | 82.4645587910243156969469573 | -0.19591761855010986253201751 | 4/0/3 | 7/7 |
| phase.memory.process_cpu_ticks | 95 | 93 | 2 | 3/0/4 | 7/7 |
| phase.concurrent-echo.successful.median_nanos | 1112788.5 | 1006307.5 | -106481 | 7/0/0 | 7/7 |
| phase.concurrent-echo.successful.p95_nanos | 1968502 | 1705372 | -331164 | 7/0/0 | 7/7 |
| phase.concurrent-echo.successful.p99_nanos | 2299686 | 1928590 | -275470 | 6/0/1 | 7/7 |
| phase.concurrent-echo.all_offered.p99_nanos | 2444128 | 2041623 | -231675 | 7/0/0 | 7/7 |
| phase.concurrent-echo.backend_setup_micros.median | 67 | 36 | -29 | 7/0/0 | 7/7 |
| phase.concurrent-echo.guest_call_micros.median | 66.5 | 53.5 | -13 | 6/0/1 | 7/7 |
| phase.concurrent-echo.activation_resource_reclamation_micros.median | 35 | 31.5 | -4 | 6/0/1 | 7/7 |
| phase.concurrent-echo.throughput_rps | 935.4740341093565491678392065 | 1015.354073241201691218166131 | 55.1015293743290002036270553 | 2/0/5 | 7/7 |
| phase.concurrent-echo.process_cpu_ticks | 20 | 19 | -1 | 5/1/1 | 7/7 |

## speed-and-size-on-demand

| Metric (original units) | Baseline median | Candidate median | Median paired delta | Lower/equal/higher | Available pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| fresh_engine_first_echo.latency_nanos | 36030747 | 35192727 | 1617460 | 3/0/4 | 7/7 |
| derived.preparation.component_new.median_nanos | 33250055 | 33727406 | 1037597.5 | 3/0/4 | 7/7 |
| preparation.component_new.total_cpu_ticks | 22 | 22 | -1 | 4/0/3 | 7/7 |
| process.population_and_controls.cpu_seconds | 2.82 | 2.84 | -0.01 | 4/0/3 | 7/7 |
| derived.memory.vm_size_bytes.maximum | 863141888 | 863141888 | 0 | 0/7/0 | 7/7 |
| derived.memory.vm_peak_bytes.maximum | 18319851520 | 18319851520 | 0 | 0/7/0 | 7/7 |
| derived.memory.rss_bytes.maximum | 33480704 | 33587200 | 294912 | 2/0/5 | 7/7 |
| derived.memory.vm_hwm_bytes.maximum | 36667392 | 36794368 | 262144 | 1/0/6 | 7/7 |
| raw.before-shutdown.resident.compiled_image_bytes | 743312 | 743312 | 0 | 0/7/0 | 7/7 |
| phase.echo.successful.median_nanos | 609138 | 608983.5 | -6321 | 6/0/1 | 7/7 |
| phase.echo.successful.p95_nanos | 1042597 | 1028278 | -19267 | 4/0/3 | 7/7 |
| phase.echo.successful.p99_nanos | 1351423 | 1322651 | -127820 | 4/0/3 | 7/7 |
| phase.echo.all_offered.p99_nanos | 1579220 | 1399023 | -169549 | 5/0/2 | 7/7 |
| phase.echo.backend_setup_micros.median | 51 | 50 | -1 | 4/1/2 | 7/7 |
| phase.echo.guest_call_micros.median | 53 | 52.5 | -0.5 | 4/2/1 | 7/7 |
| phase.echo.activation_resource_reclamation_micros.median | 27 | 26 | 0 | 3/2/2 | 7/7 |
| phase.echo.throughput_rps | 660.3413722218932896761841915 | 654.696193820726246729655435 | -5.2635823866954485325601425 | 4/0/3 | 7/7 |
| phase.echo.process_cpu_ticks | 68 | 68 | 0 | 3/1/3 | 7/7 |
| phase.compute.successful.median_nanos | 1204083.5 | 1242858 | 33005 | 2/0/5 | 7/7 |
| phase.compute.successful.p95_nanos | 1977624 | 2044674 | 20770 | 3/0/4 | 7/7 |
| phase.compute.successful.p99_nanos | 2361645 | 2541542 | 54480 | 3/0/4 | 7/7 |
| phase.compute.all_offered.p99_nanos | 2442229 | 2611841 | -2769 | 4/0/3 | 7/7 |
| phase.compute.backend_setup_micros.median | 37 | 37 | 0 | 3/1/3 | 7/7 |
| phase.compute.guest_call_micros.median | 660 | 670.5 | -6 | 4/0/3 | 7/7 |
| phase.compute.activation_resource_reclamation_micros.median | 28 | 30 | 0.5 | 3/0/4 | 7/7 |
| phase.compute.throughput_rps | 452.9522673274173921844353124 | 439.787496468343200967936547 | -9.3434240103416588667850289 | 5/0/2 | 7/7 |
| phase.compute.process_cpu_ticks | 32 | 34 | 0 | 1/3/3 | 7/7 |
| phase.memory.successful.median_nanos | 11193933.5 | 10810042 | -247987 | 4/0/3 | 7/7 |
| phase.memory.successful.p95_nanos | 13182190 | 13619749 | 295822 | 2/0/5 | 7/7 |
| phase.memory.successful.p99_nanos | 14570340 | 15807406 | -109415 | 4/0/3 | 7/7 |
| phase.memory.all_offered.p99_nanos | 14764495 | 15854204 | -263210 | 4/0/3 | 7/7 |
| phase.memory.backend_setup_micros.median | 65 | 61.5 | -2.5 | 4/0/3 | 7/7 |
| phase.memory.guest_call_micros.median | 10097.5 | 9776.5 | 8.5 | 3/0/4 | 7/7 |
| phase.memory.activation_resource_reclamation_micros.median | 208 | 200 | -1 | 4/0/3 | 7/7 |
| phase.memory.throughput_rps | 79.5798803042999337039912155 | 81.9375769605893147185190289 | 0.78981195961217455702571201 | 3/0/4 | 7/7 |
| phase.memory.process_cpu_ticks | 95 | 92 | -1 | 4/1/2 | 7/7 |
| phase.concurrent-echo.successful.median_nanos | 1112788.5 | 1100248.5 | -25060 | 4/0/3 | 7/7 |
| phase.concurrent-echo.successful.p95_nanos | 1968502 | 1784975 | -197559 | 6/0/1 | 7/7 |
| phase.concurrent-echo.successful.p99_nanos | 2299686 | 2175135 | 16079 | 3/0/4 | 7/7 |
| phase.concurrent-echo.all_offered.p99_nanos | 2444128 | 2349212 | -10545 | 4/0/3 | 7/7 |
| phase.concurrent-echo.backend_setup_micros.median | 67 | 68.5 | -0.5 | 4/0/3 | 7/7 |
| phase.concurrent-echo.guest_call_micros.median | 66.5 | 63.5 | -6.5 | 5/0/2 | 7/7 |
| phase.concurrent-echo.activation_resource_reclamation_micros.median | 35 | 36.5 | 1.5 | 2/1/4 | 7/7 |
| phase.concurrent-echo.throughput_rps | 935.4740341093565491678392065 | 967.5366582443356454511502115 | 38.4680479352158212509569216 | 2/0/5 | 7/7 |
| phase.concurrent-echo.process_cpu_ticks | 20 | 20 | -1 | 5/1/1 | 7/7 |

## pooling-speed-and-size

| Metric (original units) | Baseline median | Candidate median | Median paired delta | Lower/equal/higher | Available pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| fresh_engine_first_echo.latency_nanos | 36030747 | 37899789 | 2848380 | 1/0/6 | 7/7 |
| derived.preparation.component_new.median_nanos | 33250055 | 36748370.5 | 3500262.5 | 0/0/7 | 7/7 |
| preparation.component_new.total_cpu_ticks | 22 | 24 | 3 | 0/1/6 | 7/7 |
| process.population_and_controls.cpu_seconds | 2.82 | 2.82 | -0.06 | 6/0/1 | 7/7 |
| derived.memory.vm_size_bytes.maximum | 863141888 | 1409159168 | 546017280 | 0/0/7 | 7/7 |
| derived.memory.vm_peak_bytes.maximum | 18319851520 | 1474879488 | -16844972032 | 7/0/0 | 7/7 |
| derived.memory.rss_bytes.maximum | 33480704 | 34447360 | 876544 | 0/0/7 | 7/7 |
| derived.memory.vm_hwm_bytes.maximum | 36667392 | 37744640 | 1204224 | 0/0/7 | 7/7 |
| raw.before-shutdown.resident.compiled_image_bytes | 743312 | 829360 | 86048 | 0/0/7 | 7/7 |
| phase.echo.successful.median_nanos | 609138 | 588194 | -15159 | 5/0/2 | 7/7 |
| phase.echo.successful.p95_nanos | 1042597 | 990629 | -46205 | 5/0/2 | 7/7 |
| phase.echo.successful.p99_nanos | 1351423 | 1335424 | -51411 | 4/0/3 | 7/7 |
| phase.echo.all_offered.p99_nanos | 1579220 | 1431782 | -195473 | 4/0/3 | 7/7 |
| phase.echo.backend_setup_micros.median | 51 | 34 | -17 | 7/0/0 | 7/7 |
| phase.echo.guest_call_micros.median | 53 | 47 | -4 | 7/0/0 | 7/7 |
| phase.echo.activation_resource_reclamation_micros.median | 27 | 25 | -2 | 6/0/1 | 7/7 |
| phase.echo.throughput_rps | 660.3413722218932896761841915 | 670.6326720461511163693481545 | -2.390621495543992241389504 | 4/0/3 | 7/7 |
| phase.echo.process_cpu_ticks | 68 | 66 | -1 | 4/0/3 | 7/7 |
| phase.compute.successful.median_nanos | 1204083.5 | 1055442.5 | -170526 | 7/0/0 | 7/7 |
| phase.compute.successful.p95_nanos | 1977624 | 1866886 | -185567 | 7/0/0 | 7/7 |
| phase.compute.successful.p99_nanos | 2361645 | 2151097 | -311589 | 5/0/2 | 7/7 |
| phase.compute.all_offered.p99_nanos | 2442229 | 2245386 | -377526 | 5/0/2 | 7/7 |
| phase.compute.backend_setup_micros.median | 37 | 20.5 | -16.5 | 7/0/0 | 7/7 |
| phase.compute.guest_call_micros.median | 660 | 495 | -168.5 | 7/0/0 | 7/7 |
| phase.compute.activation_resource_reclamation_micros.median | 28 | 17.5 | -11 | 7/0/0 | 7/7 |
| phase.compute.throughput_rps | 452.9522673274173921844353124 | 465.0816683409606726941250884 | 22.2416284111142310328981946 | 1/0/6 | 7/7 |
| phase.compute.process_cpu_ticks | 32 | 33 | -1 | 4/1/2 | 7/7 |
| phase.memory.successful.median_nanos | 11193933.5 | 10060940 | -1152253.5 | 7/0/0 | 7/7 |
| phase.memory.successful.p95_nanos | 13182190 | 12451217 | -1128323 | 7/0/0 | 7/7 |
| phase.memory.successful.p99_nanos | 14570340 | 13967760 | -160680 | 4/0/3 | 7/7 |
| phase.memory.all_offered.p99_nanos | 14764495 | 14076515 | -183943 | 4/0/3 | 7/7 |
| phase.memory.backend_setup_micros.median | 65 | 38.5 | -26 | 7/0/0 | 7/7 |
| phase.memory.guest_call_micros.median | 10097.5 | 9065 | -1004 | 7/0/0 | 7/7 |
| phase.memory.activation_resource_reclamation_micros.median | 208 | 188 | -17.5 | 6/0/1 | 7/7 |
| phase.memory.throughput_rps | 79.5798803042999337039912155 | 86.11762213410409968672373625 | 6.39026933592270759884240149 | 0/0/7 | 7/7 |
| phase.memory.process_cpu_ticks | 95 | 89 | -5 | 7/0/0 | 7/7 |
| phase.concurrent-echo.successful.median_nanos | 1112788.5 | 1019331.5 | -111921 | 7/0/0 | 7/7 |
| phase.concurrent-echo.successful.p95_nanos | 1968502 | 1749316 | -339608 | 5/0/2 | 7/7 |
| phase.concurrent-echo.successful.p99_nanos | 2299686 | 2257491 | -81683 | 4/0/3 | 7/7 |
| phase.concurrent-echo.all_offered.p99_nanos | 2444128 | 2409304 | -29385 | 4/0/3 | 7/7 |
| phase.concurrent-echo.backend_setup_micros.median | 67 | 35 | -30 | 7/0/0 | 7/7 |
| phase.concurrent-echo.guest_call_micros.median | 66.5 | 53.5 | -13.5 | 6/0/1 | 7/7 |
| phase.concurrent-echo.activation_resource_reclamation_micros.median | 35 | 32 | -3 | 7/0/0 | 7/7 |
| phase.concurrent-echo.throughput_rps | 935.4740341093565491678392065 | 978.441142526639416927965871 | 57.575295009022489562220273 | 1/0/6 | 7/7 |
| phase.concurrent-echo.process_cpu_ticks | 20 | 20 | -1 | 4/3/0 | 7/7 |

All seven pair values, percentages, order strata, full metric tables and availability reasons are retained in the adjacent JSON.

## Scope

- Reporting checks are not another full semantic replay; publication replay/CI receipts remain separate.
- Seven process observations per row; median paired delta is not difference of row medians. No pooled individual-call estimate.
- Three configuration contrasts reuse the same actual candidate D0 in each block. Order strata are small descriptive subsets.
- Successful latency is conditional on success. All-offered counts, warmups, intentional faults and budget misses remain retained.
- Matrix throughput includes Invoke, status, validation and retention; external throughput spans scheduled measured offers to completion.
- Matrix CPU combines node/client/observation work; external server and client CPU cover their full batches including warmup.
- Compilation stages overlap. Do not sum whole_job CPU/time with its child stages or infer totals from a stage median.
- Virtual mappings, kernel high-water fields, sampled RSS, smaps values and compiled-image span charges are distinct.
- Missing values are unavailable, never zero. No allocation-per-call, physical-pool-slot, universal speedup or SLO claim.
- Historical #104/#105 medians are not subtracted. External default D0 results do not qualify P0/D1/P1 external performance.
- The maintained Echo guest emits its result log in both arms. The corrected replay oracle checks this existing behavior; logging is not removed from timings.
