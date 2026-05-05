# Bitcoin On-Chain Analytics (2017-2026)

Full ETL pipeline and OLAP analysis of Bitcoin's UTXO system and fee dynamics during the modern exchange era. Built with Bitcoin Core, Parquet, ClickHouse, and Python/JupyterLab.

## Phases

Phase 1 - UTXO Analysis: Value distribution, age cohorts, script evolution. Done.
Phase 2 - Fees Over Time: Daily fees, moving averages, halving impact. Done.
Phase 3 - Quantitative Momentum Signal. Pending.
Phase 4 - Mempool Heatmap Dashboard. Pending.
Phase 5 - Fees Prediction Model. Pending.
Phase 6 - Entity Clustering. Pending.

## System Architecture

Three-layer ETL pipeline with zero data duplication. Bitcoin Core with txindex=1 serves as source of truth. Data flows through three Parquet layers, each building on the previous. ClickHouse reads Parquet files directly via File engine — no import step, no data duplication, no extra storage.

Layer 1 (capa1_btccore_parquet): Raw blockchain data extracted via RPC — blocks, transactions, inputs, outputs. Partitioned by block height in 250-block batches.

Layer 2 (capa2_utxo_parquet): Normalized UTXO events. Every output becomes a create event, every input becomes a spend event. Fields include event_type, height, txid, outpoint, value_sats, scriptPubKey_type, spent_by.

Layer 3 (capa3_block_metrics): Pre-computed block-level metrics. Each block gets its subsidy (halving-aware) and total fees calculated from coinbase outputs. Eliminates expensive JOINs at query time.

Stack: Bitcoin Core RPC to Python ETL to Parquet (zstd) to ClickHouse File Engine to JupyterLab (pandas, matplotlib).

Design decisions: 250 blocks per Parquet file for optimal I/O. zstd compression level 6. State JSON files enable pause/resume without duplication. Menu-driven ETL with reset, continue, and rollback options. ClickHouse reads Parquet directly from user_files symlinks. No data duplication between Parquet and ClickHouse.

## ETL Pipeline

Scripts:

etl/capa1_btccore_parquet.py — Extracts blocks, txs, inputs, outputs from Bitcoin Core RPC. Writes to parquet/capa1_btccore_parquet/. State file: state_capa1_btccore_parquet.json.

etl/capa2_utxo_parquet.py — Reads Capa 1 inputs and outputs, normalizes into UTXO create/spend events. Writes to parquet/capa2_utxo_parquet/utxo_events/. State file: state_capa2_utxo_parquet.json.

etl/capa3_block_metrics.py — Reads Capa 1 blocks, inputs, and outputs. Calculates fees per block as coinbase outputs minus block subsidy. Writes to parquet/capa3_block_metrics/blocks/. State file: state_capa3_block_metrics.json.

Features: Automatic retries with exponential backoff. Reorg detection and safe rollback. Batch RPC calls with dynamic chunk sizing. Prefetch caching for reduced latency. tqdm progress bars. 948,312 blocks processed from height 0 to 948,069.

## Phase 1 - UTXO Analysis

Notebook: notebooks/01_exploracion_utxo.ipynb

Comprehensive quantitative analysis of Bitcoin's UTXO system structure. Examines value distribution, age cohort behavior, script type evolution, and outlier patterns across the modern era.

Key findings:

Heavy-Tail Distribution: UTXO values exhibit extreme skewness spanning 10 orders of magnitude. Small medians with very long tails, consistent with decentralized systems where few entities hold disproportionate value.

Age Cohorts: The majority of supply resides in UTXOs aged 5-10 years, followed by 2-5 years. Younger cohorts under 6 months contain small, high-velocity outputs. This reflects long-term holding behavior and historical consolidation waves.

Zero Value-Age Correlation: value_sats and age_days show no meaningful correlation. Bitcoin does not exhibit value by age behavior. UTXO value is independent of its lifespan.

Script Evolution: Clear technological progression from Legacy (P2PKH, P2SH) to SegWit (P2WPKH, P2WSH) to Taproot (v1). Legacy scripts persist mainly in older cohorts while SegWit dominates younger ones. Taproot appears in recent years.

Institutional Consolidations: Top 0.1 percent of UTXOs show enormous values clustered at specific block heights. These correspond to exchange reorganizations, hot-to-cold migrations, and large batching operations.

Visualizations: boxplot_value_by_age.png shows distribution of log10 value_sats by age cohort. heatmap_correlation.png confirms zero correlation between value and age. scatter_value_vs_age.png reveals structural independence. kde_by_age_bucket.png shows value distribution patterns across holding periods. pivot_script_vs_age.png shows SegWit to Taproot migration across time.

## Phase 2 - Fees Over Time (Binance Era)

Notebook: notebooks/02_fees_over_time.ipynb

Temporal analysis of Bitcoin transaction fees during the modern exchange era. Period starts July 14, 2017 (Binance launch) through May 5, 2026.

Key metrics:

Period: July 14, 2017 to May 5, 2026. Days analyzed: 3,218. Total fees: 192,552 BTC. Mean daily fees: 59.84 BTC. Median daily fees: 23.04 BTC. Max daily fees: 1,369.48 BTC on December 22, 2017. Halving 2024 day fees: 861.14 BTC ranked number 5 all-time.

Top 10 fee days:

1. December 22, 2017 - 1,369.48 BTC (146 blocks) - 2017 bull peak
2. December 21, 2017 - 1,233.58 BTC (137 blocks) - 2017 bull peak
3. December 23, 2017 - 1,068.56 BTC (146 blocks) - 2017 bull peak
4. December 20, 2017 - 962.49 BTC (136 blocks) - 2017 bull peak
5. April 20, 2024 - 861.14 BTC (134 blocks) - Halving day
6. December 29, 2017 - 807.73 BTC (161 blocks) - 2017 bull peak
7. December 24, 2017 - 794.93 BTC (150 blocks) - 2017 bull peak
8. December 27, 2017 - 792.13 BTC (156 blocks) - 2017 bull peak
9. January 3, 2018 - 771.30 BTC (160 blocks) - 2017 bull peak
10. December 28, 2017 - 756.42 BTC (149 blocks) - 2017 bull peak

Key findings:

2017 Dominance: 9 of the top 10 highest-fee days occurred during the December 2017 to January 2018 bull market peak, when Bitcoin first reached twenty thousand dollars.

Halving 2024 Impact: April 20, 2024 halving day generated 861.14 BTC in fees, ranking number 5 all-time and breaking the 2017 monopoly on top fee days. Halving day fee premium driven by speculative activity and block space competition.

Heavy-Tail Confirmed: Mean daily fees of 59.84 BTC is 2.6 times the median of 23.04 BTC, confirming fee spikes dominate cumulative totals. A small number of extreme-fee days account for disproportionate share of total fees.

Cyclical Pattern: MA30 smoothing reveals clear 4-year market cycles aligned with Bitcoin halving epochs. Fee peaks correspond to bull market tops in 2017, 2021, and 2025.

Post-Halving Elevation: Fees in 2024-2026 remain structurally higher than the 2022-2023 bear market, suggesting increased demand for block space from Ordinals, Runes, and Layer 2 settlement.

Visualizations: fees_over_time_binance_era.png shows full Binance Era on log scale with daily fees as orange bars, 7-day MA in blue, 30-day MA in orange line, red dashed lines marking 2020 and 2024 halvings. fees_binance_era_linear.png shows same data on linear scale to highlight 2017 spike magnitude. fees_last_2_years_binance_era.png shows zoomed view of May 2024 to May 2026 with halving day marker.

## Repository Structure

btc-etl contains etl directory with 3 Python scripts, notebooks directory with 2 Jupyter notebooks and images subdirectory containing 8 PNG files (5 from Phase 1, 3 from Phase 2), parquet directory with 3 capa subdirectories (gitignored), state JSON files (gitignored), logs directory (gitignored), config directory, venvetl and venvquant virtual environments, and README.md.

## Quick Start

Start ClickHouse from /media/SSD4T/clickhouse. Run ETL scripts with venvetl environment using menu options 1 for reset, 2 for continue, or 3 for rollback. Launch JupyterLab with venvquant environment. ClickHouse tables are auto-created with File Parquet engine pointing to user_files symlinks.

Built by Byron. Stack: Bitcoin Core to Python ETL to Parquet with zstd to ClickHouse File Engine to JupyterLab with pandas and matplotlib.
