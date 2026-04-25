# 🟩 README — Phase 1: UTXO Analysis (2017–2026)

## 1. Executive Summary

This project delivers a full quantitative analysis of Bitcoin’s UTXO system during the modern era (2017–2026). It is built on a real ETL pipeline that extracts, transforms, and analyzes on‑chain data using Bitcoin Core, Parquet, ClickHouse, and Python/JupyterLab. The goal is to convert raw blockchain data into an efficient analytical model capable of revealing structural patterns, temporal behavior, value distribution, and script evolution across the UTXO set.

The results show a mature ecosystem characterized by strong value concentration in older cohorts, progressive adoption of SegWit and Taproot, heavy‑tail value distributions, and large outliers linked to institutional consolidation events. Phase 1 establishes the analytical foundation for deeper research such as entity clustering, spending behavior, ownership heuristics, dynamic cohorts, and quantitative on‑chain signals.

---

## 2. System Architecture (High‑Level Overview)

### Bitcoin Core — Source of Truth
A full node with `txindex=1` is used to extract blocks, transactions, inputs, outputs, and scripts via RPC. This ensures complete, verifiable, and reproducible raw data.

### Parquet RAW — Storage Layer
Extracted data is stored in Parquet format, partitioned by block height:

- blocks  
- txs  
- inputs  
- outputs  
- utxo_events  

This layer is columnar, compressed, and optimized for large‑scale processing.

### ClickHouse — OLAP Layer
Parquet files are imported into ClickHouse, enabling:

- high‑volume analytical queries  
- fast aggregations  
- efficient joins  
- height‑ordered storage  

The core analytical table is `utxo_events`, which normalizes every UTXO creation and spend.

### Python + JupyterLab — Analysis Layer
Used for:

- temporal enrichment (timestamps, age_days)  
- cohort construction  
- heavy‑tail analysis  
- correlation studies  
- outlier detection  
- script evolution analysis  
- visualization and interpretation  

---

## 3. ETL Pipeline (Extract → Transform → Load)

### Extract — Bitcoin Core RPC
The pipeline iterates through blocks and transactions, generating normalized UTXO events (`create` / `spend`).  
A `state.json` file ensures resumability without duplication.

### Transform — Normalization and Parquet
Raw data is transformed into clean, partitioned Parquet tables.  
`utxo_events` includes:

- event_type  
- height  
- txid  
- outpoint  
- value_sats  
- scriptPubKey_type  
- spent_by  

### Load — ClickHouse
Parquet files are loaded into ClickHouse, enabling OLAP‑scale analysis across the entire blockchain.

### Analyze — Python/Jupyter
Performed analyses include:

- age cohorts  
- heavy‑tail distributions  
- correlation matrices  
- outlier identification  
- script‑type evolution  
- multi‑dimensional visualizations  

---

## 4. Key Findings

### Heavy‑Tail Distribution of UTXO Value
UTXO values exhibit extreme skewness, with small medians and very long tails. Massive outliers appear across all cohorts, consistent with decentralized financial systems where a small number of entities hold disproportionate value.

### 5–10 Year Cohorts Dominate Total Value
The majority of supply resides in UTXOs aged 5–10 years, followed by 2–5 years.  
Younger cohorts (<6 months) contain small, high‑velocity outputs.  
This reflects long‑term holding behavior and historical consolidation waves.

### Massive Outliers = Institutional Consolidations
The top 0.1% of UTXOs show enormous values, often clustered at specific block heights.  
These correspond to:

- exchange reorganizations  
- hot‑to‑cold migrations  
- large batching operations  

### Zero Correlation Between Value and Age
`value_sats` and `age_days` show no meaningful correlation.  
Bitcoin does not exhibit “value by age” behavior — UTXO value is independent of its lifespan.

### Script‑Type Evolution (2017–2026)
Clear technological progression:

- SegWit (P2WPKH, P2WSH) dominates younger cohorts  
- Legacy (P2PKH, P2SH) persists mainly in older cohorts  
- Taproot (v1) appears in recent years  
- Non‑standard scripts remain marginal  

### Aged and Stable Supply
The UTXO set is dominated by old supply with low turnover, consistent with:

- long‑term accumulation  
- institutional custody  
- reduced sell pressure  
- structural maturity of the ecosystem  

---

## Conclusions

The modern UTXO system is:

- structurally stable  
- dominated by older cohorts  
- technologically evolving toward SegWit and Taproot  
- influenced by institutional consolidation patterns  
- statistically independent in value vs. age  

Phase 1 provides a robust analytical foundation for:

- spending behavior analysis  
- entity clustering  
- ownership heuristics  
- dynamic cohort modeling  
- quantitative on‑chain indicators  

---

## 5. Visualization Highlights

### Distribution of log10(value_sats) by Age Cohort
![boxplot_value_by_age](notebooks/images/boxplot_value_by_age.png)

### Correlation Heatmap
![heatmap_correlation](notebooks/images/heatmap_correlation.png)

### Scatter: log10(value_sats) vs age_days
![scatter_value_vs_age](notebooks/images/scatter_value_vs_age.png)

### KDE by Age Cohort
![kde_by_age_bucket](notebooks/images/kde_by_age_bucket.png)

### Supply by Script Type and Age Cohort
![pivot_script_vs_age](notebooks/images/pivot_script_vs_age.png)

