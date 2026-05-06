# Bitcoin On-Chain Analytics (2017-2026)

Full ETL pipeline and OLAP analysis of Bitcoin's UTXO system, fee dynamics, and quantitative momentum signals during the modern exchange era. Built with Bitcoin Core, Parquet, ClickHouse, and Python/JupyterLab.

## Phases

Phase 1 - UTXO Analysis: Value distribution, age cohorts, script evolution. Done.
Phase 2 - Fees Over Time: Daily fees, moving averages, halving impact. Done.
Phase 3 - Momentum Signal: Fee Z-Score, price divergence, regime detection. Done.
Phase 4 - Mempool Heatmap Dashboard. Pending.
Phase 5 - LightGBM Fees Prediction Model. Pending.
Phase 6 - Entity Clustering. Pending.
Phase 7 - Apache Superset Unified Dashboard. Pending.
Phase 8 - LightGBM Trading Bot. Pending.

## System Architecture

Four-layer ETL pipeline with zero data duplication. Bitcoin Core with txindex=1 serves as source of truth. ClickHouse reads Parquet files directly via File engine. No import step, no data duplication, no extra storage.

Layer 1 (capa1_btccore_parquet): Raw blockchain data via RPC — blocks, transactions, inputs, outputs. Partitioned by block height in 250-block batches.

Layer 2 (capa2_utxo_parquet): Normalized UTXO events. Every output becomes a create event, every input becomes a spend event.

Layer 3 (capa3_block_metrics): Pre-computed block-level metrics. Fees calculated as coinbase outputs minus block subsidy. Eliminates expensive JOINs.

Layer 4 (capa4_binance): BTC/USDT price data from Binance API. 1-minute and 1-day candles with derived metrics (returns, volatility, VWAP).

Stack: Bitcoin Core RPC + Binance API to Python ETL to Parquet (zstd) to ClickHouse File Engine to JupyterLab (pandas, matplotlib).

Design decisions: 250 units per batch. zstd compression level 6. State JSON files for pause/resume. Menu-driven ETL (1=reset, 2=continue, 3=rollback). ClickHouse reads Parquet from user_files symlinks. Zero data duplication.

## ETL Pipeline

etl/capa1_btccore_parquet.py — Extracts on-chain data from Bitcoin Core RPC. 948,312 blocks processed (heights 0 to 948,069).

etl/capa2_utxo_parquet.py — Normalizes UTXO create/spend events from Capa 1. 7.08 billion events.

etl/capa3_block_metrics.py — Calculates fees and subsidy per block. 301,789 BTC total fees identified.

etl/capa4_binance.py — Downloads BTC/USDT from Binance API. 4.58M 1m candles, 3,185 daily candles.

Features: Automatic retries with exponential backoff. Reorg detection and safe rollback. tqdm progress bars. State machine architecture.

## Phase 1 - UTXO Analysis

Notebook: notebooks/01_exploracion_utxo.ipynb

Comprehensive UTXO system structure analysis. Value distribution, age cohort behavior, script type evolution, outlier patterns.

Key findings: Heavy-tail distribution spanning 10 orders of magnitude. 5-10 year cohorts hold majority supply. Zero correlation between value and age. Clear Legacy to SegWit to Taproot progression. Institutional consolidations visible in top 0.1% outliers.

![Boxplot by Age](notebooks/images/boxplot_value_by_age.png)
![Correlation Heatmap](notebooks/images/heatmap_correlation.png)
![Scatter Value vs Age](notebooks/images/scatter_value_vs_age.png)
![KDE by Age](notebooks/images/kde_by_age_bucket.png)
![Script vs Cohort](notebooks/images/pivot_script_vs_age.png)

## Phase 2 - Fees Over Time (Binance Era)

Notebook: notebooks/02_fees_over_time.ipynb

Temporal fee analysis from Binance launch (July 14, 2017) through May 2026. 3,218 days. 192,552 BTC total fees.

Key metrics: Mean 59.84 BTC/day. Median 23.04 BTC/day. Max 1,369.48 BTC (Dec 22, 2017). Halving 2024: 861.14 BTC (#5 all-time).

Top 10 fee days: 9 of 10 during Dec 2017-Jan 2018 bull peak. April 20, 2024 halving breaks 2017 monopoly at #5.

Key findings: 2017 dominance with heavy-tail confirmed (mean 2.6x median). MA30 reveals 4-year cyclical patterns. Post-2024 fees structurally elevated.

![Fees Log Scale](notebooks/images/fees_over_time_binance_era.png)
![Fees Linear Scale](notebooks/images/fees_binance_era_linear.png)
![Fees Last 2 Years](notebooks/images/fees_last_2_years_binance_era.png)

## Phase 3 - Quantitative Momentum Signal

Notebook: notebooks/03_momentum_signal.ipynb

Z-Score based momentum signal using on-chain fees and BTC price. 30-day rolling window with MA7 smoothing. Regime classification: elevated, normal, depressed.

Key metrics: 148 elevated streaks detected across 3,185 days. Signal threshold at Z > 1.5 for elevated, Z < -1.5 for depressed.

Top 10 strongest signals:
1. Apr 10, 2026 — Z=5.29 (post-halving 2026)
2. Aug 22, 2024 — Z=5.28 (summer fee spike)
3. Jun 7, 2024 — Z=5.16 (post-halving demand)
4. Jun 19, 2018 — Z=5.06 (bear market bounce)
5. Feb 23, 2025 — Z=4.94 (correction low)
6. Apr 19, 2024 — Z=4.87 (halving eve)
7. May 7, 2023 — Z=4.72 (Ordinals peak)
8. Apr 24, 2018 — Z=4.68 (bear rally)
9. Apr 11, 2026 — Z=4.64 (halving 2026)
10. Apr 30, 2020 — Z=4.64 (pre-halving 2020)

Key findings: All 3 halvings detected with Z > 4.5. Longest streak: 14 days during Ordinals 2023. Fee/Price divergence identifies demand-leading vs speculation-leading regimes.

Actionable thresholds: Z > +2 exhaustion (sell), Z < -2 accumulation (buy), Z between -1.5 and +1.5 normal (hold).

![Momentum Z-Score](notebooks/images/momentum_fee_zscore.png)
![Momentum Divergence](notebooks/images/momentum_divergence.png)

## Repository Structure

btc-etl/ with etl/ (4 Python scripts), notebooks/ (3 Jupyter notebooks + images/ with 10 PNGs), parquet/ (4 capa directories, gitignored), state JSON files (gitignored), logs/ (gitignored), config/, venvetl/, venvquant/, README.md.

## Quick Start

Start ClickHouse from /media/SSD4T/clickhouse. Run ETL scripts with venvetl (options 1/2/3). Launch JupyterLab with venvquant. ClickHouse tables use File(Parquet) engine via user_files/ symlinks.

Built by Byron. Stack: Bitcoin Core + Binance API to Python ETL to Parquet (zstd) to ClickHouse File Engine to JupyterLab (pandas, matplotlib).
