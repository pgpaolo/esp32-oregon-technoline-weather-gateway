# RC6-stab1-rain1 MBFIX1 — Source-only follow-up / Correzione accumulo pioggia COMPATIBLE MB

**Tag:** `v6.4.0-rc6-stab1-rain1-mbfix1`  
**Date / Data:** 2026-10-09  
**Original immutable rain1 release:** [`v6.4.0-rc6-stab1-rain1`](https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway/releases/tag/v6.4.0-rc6-stab1-rain1)  
**Implementation commit:** `4b58c68b6ad78a0a9be841be38a7e470f428e44e`  
**Source branch:** `release/6.4.0-rc6-stab1-rain1`  
**Status / Stato:** Source-only prerelease. **Not physically certified**; no board-ready `.bin` distributed in this release.

## Why / Perché

The historical COMPATIBLE MB publisher calculated its own daily rainfall from separate baseline counters in MB NVS. This could disagree with the dedicated Oregon/Technoline rainfall accumulator shown in `GET /api/rain/accumulation`, especially around reception gaps, first data samples or UTC day changes.

La versione precedente aveva un contatore giornaliero indipendente per il publisher MB. Questa patch usa il **medesimo accumulatore giornaliero UTC** previsto dal modulo pioggia, evitando due sorgenti di verità per il valore giornaliero.

## Changes / Modifiche

| MB field | Current semantics / Nuova semantica |
|---|---|
| 9 (rain today / pioggia oggi) | Shared `rainAccumulatorTodayMm` of the **selected** Oregon or Technoline source for the current UTC day. |
| 151 (rain total / totale sensore) | **Unchanged**, reported cumulative sensor total. |
| Rain instantaneous/rate and rolling windows | Still subject to freshness/availability checks. |
| Unavailable daily accumulator | `--` if disabled, not yet initialized or UTC invalid; no fabricated zero. |
| Short RF reception gap | Retained daily accumulated value can remain available even when no fresh rain frame is received. |

The separate MB daily NVS baselines (`orDay/orBase/lcDay/lcBase`) are no longer read/updated by the publisher. Existing MB network and publishing configuration is retained; this patch does **not** reset existing rainfall history. Historical unused MB baseline keys may remain physically present in NVS.

## Operation / Configurazione

1. Under **CONFIGURAZIONE > microSD**, enable rain accumulation for the chosen Oregon and/or Technoline source. Select the desired source under **COMPATIBLE MB**.
2. Use a working UTC time source. The daily bucket boundary is **UTC**, not necessarily the local civil midnight.
3. When SD checkpoint persistence is disabled or the card is unavailable, retained daily accumulation is not guaranteed across a power cycle. On a new uninitialized accumulator, the **first** accepted rain sample establishes the baseline; previously fallen rain is not reconstructed.
4. Compare `GET /api/rain/accumulation` and the outgoing COMPATIBLE MB payload **field 9** for the same source and UTC day. Do not confuse daily rainfall with MB field 151 sensor lifetime total.
5. During a temporary radio pause, the daily total should remain coherent, while rate and rolling-window measurements retain their own validity rules.
6. Confirm clean UTC rollover and recovery after reboot using controlled tests before continuous deployment.

## Validation / Verifica

- **Implementation commit `4b58c68b6ad78a0a9be841be38a7e470f428e44e`**: automated rainfall arithmetic host test **PASS**, COMPATIBLE MB mapping regression **PASS**, PlatformIO builds for `t3-v161-433` and `t3-s3-433` **PASS**. [Workflow run](https://github.com/pgpaolo/esp32-oregon-technoline-weather-gateway/actions/runs/37945245203).
- Publication workflow is configured to rebuild/test the precise follow-up Git commit **before** creating this release. Check its final status and tag identity on GitHub.
- **Not yet tested/certified on physical hardware as this complete follow-up firmware:** live SX1278, steady RF, NVS/SD cold-start restoration, full UTC boundary, networking/MQTT concurrency, hardware OTA and long-running heap behavior remain field acceptance tasks.
- This is **not** a merge to `main`, `develop` or `release/6.4.0-rc6-stab2-hardening`; later integration requires a separate review.

## Related documentation / Documentazione

- [Original rain1 notes](RELEASE_6.4.0_RC6_STAB1_RAIN1.md)
- [Italian rainfall guide](RAIN_ACCUMULATION.md) · [English rainfall guide](RAIN_ACCUMULATION_EN.md)
- [MB compatible guide](MB_COMPATIBLE.md) · [HTTP API](API.md)
- [Publication policy](../PUBLISHING_RAIN1.md)

**License:** GPL-3.0-or-later. Never publish local passwords, private station identities or user-specific endpoints with test logs.
