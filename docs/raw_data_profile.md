# Raw Data Profile

## 1. Inventory
### data/raw/fundamentals/
Example paths:
- fundamentals/alphaV/AAPL/2026/01/13/1001/AAPL.parquet
- fundamentals/alphaV/AMD/2026/01/13/1001/AMD.parquet
- fundamentals/alphaV/AMZN/2026/01/13/1001/AMZN.parquet
- fundamentals/alphaV/DIS/2026/01/13/1001/DIS.parquet
- fundamentals/alphaV/GOOGL/2026/01/13/1001/GOOGL.parquet
- fundamentals/alphaV/INTC/2026/01/13/1001/INTC.parquet
- fundamentals/alphaV/JPM/2026/01/13/1001/JPM.parquet
- fundamentals/alphaV/MA/2026/01/13/1001/MA.parquet
- fundamentals/alphaV/META/2026/01/13/1001/META.parquet
- fundamentals/alphaV/MSFT/2026/01/13/1001/MSFT.parquet
- fundamentals/alphaV/NFLX/2026/01/13/1001/NFLX.parquet
- fundamentals/alphaV/NVDA/2026/01/13/1001/NVDA.parquet
- fundamentals/alphaV/TSLA/2026/01/13/1001/TSLA.parquet
- fundamentals/alphaV/V/2026/01/13/1001/V.parquet
- fundamentals/finnhub/AAPL/2026/01/13/1001/AAPL.parquet
- fundamentals/finnhub/AMD/2026/01/13/1001/AMD.parquet
- fundamentals/finnhub/AMZN/2026/01/13/1001/AMZN.parquet
- fundamentals/finnhub/DIS/2026/01/13/1001/DIS.parquet
- fundamentals/finnhub/GOOGL/2026/01/13/1001/GOOGL.parquet
- fundamentals/finnhub/INTC/2026/01/13/1001/INTC.parquet
- ... (8 more)

### data/raw/prices/
Example paths:
- prices/AAPL.US/2026/01/13/1001/prices_AAPL.US.parquet
- prices/AMD.US/2026/01/13/1001/prices_AMD.US.parquet
- prices/AMZN.US/2026/01/13/1001/prices_AMZN.US.parquet
- prices/DIS.US/2026/01/13/1001/prices_DIS.US.parquet
- prices/GOOGL.US/2026/01/13/1001/prices_GOOGL.US.parquet
- prices/INTC.US/2026/01/13/1001/prices_INTC.US.parquet
- prices/JPM.US/2026/01/13/1001/prices_JPM.US.parquet
- prices/MA.US/2026/01/13/1001/prices_MA.US.parquet
- prices/META.US/2026/01/13/1001/prices_META.US.parquet
- prices/MSFT.US/2026/01/13/1001/prices_MSFT.US.parquet
- prices/NFLX.US/2026/01/13/1001/prices_NFLX.US.parquet
- prices/NVDA.US/2026/01/13/1001/prices_NVDA.US.parquet
- prices/TSLA.US/2026/01/13/1001/prices_TSLA.US.parquet
- prices/V.US/2026/01/13/1001/prices_V.US.parquet
- prices/alphaV/AAPL.US/2026/01/13/1001/alphaV_AAPL.US.parquet
- prices/alphaV/AMZN.US/2026/01/13/1001/alphaV_AMZN.US.parquet
- prices/alphaV/GOOGL.US/2026/01/13/1001/alphaV_GOOGL.US.parquet
- prices/alphaV/META.US/2026/01/13/1001/alphaV_META.US.parquet
- prices/alphaV/TSLA.US/2026/01/13/1001/alphaV_TSLA.US.parquet

### data/raw/sentiment/
Example paths:
- sentiment/AAPL/2026/01/13/1001/sentiment_AAPL_newsapi.parquet
- sentiment/AAPL/2026/01/13/1001/sentiment_AAPL_reddit.parquet
- sentiment/AMZN/2026/01/13/1001/sentiment_AMZN_newsapi.parquet
- sentiment/AMZN/2026/01/13/1001/sentiment_AMZN_reddit.parquet
- sentiment/GOOGL/2026/01/13/1001/sentiment_GOOGL_newsapi.parquet
- sentiment/GOOGL/2026/01/13/1001/sentiment_GOOGL_reddit.parquet
- sentiment/META/2026/01/13/1001/sentiment_META_newsapi.parquet
- sentiment/META/2026/01/13/1001/sentiment_META_reddit.parquet
- sentiment/MSFT/2026/01/13/1001/sentiment_MSFT_newsapi.parquet
- sentiment/MSFT/2026/01/13/1001/sentiment_MSFT_reddit.parquet
- sentiment/NVDA/2026/01/13/1001/sentiment_NVDA_newsapi.parquet
- sentiment/NVDA/2026/01/13/1001/sentiment_NVDA_reddit.parquet
- sentiment/TSLA/2026/01/13/1001/sentiment_TSLA_newsapi.parquet
- sentiment/TSLA/2026/01/13/1001/sentiment_TSLA_reddit.parquet
- sentiment/economy/2026/01/13/1001/sentiment_economy_newsapi.parquet
- sentiment/economy/2026/01/13/1001/sentiment_economy_reddit.parquet

## 2. Prices - per provider
### Provider: stooq (raw prices in data/raw/prices/<TICKER>/...)
Example file: `data/raw/prices/AAPL.US/2026/01/13/1001/prices_AAPL.US.parquet`
Rows: 2020, Cols: 7
Date coverage: 2018-01-02 00:00:00 -> 2026-01-14 00:00:00
Duplicates (ticker+date): 0
Schema:
| column | dtype | null_pct |
|---|---|---|
| date | datetime64[ns] | 0.0 |
| open | float64 | 0.0 |
| high | float64 | 0.0 |
| low | float64 | 0.0 |
| close | float64 | 0.0 |
| volume | int64 | 0.0 |
| ticker | object | 0.0 |

### Provider: alphaV (raw prices in data/raw/prices/alphaV/<TICKER>/...)
Example file: `data/raw/prices/alphaV/AMZN.US/2026/01/13/1001/alphaV_AMZN.US.parquet`
Rows: 100, Cols: 5
Schema:
| column | dtype | null_pct |
|---|---|---|
| open | float64 | 0.0 |
| high | float64 | 0.0 |
| low | float64 | 0.0 |
| close | float64 | 0.0 |
| volume | float64 | 0.0 |

## 3. Fundamentals - raw
### Provider: alphaV
Example file: `data/raw/fundamentals/alphaV/GOOGL/2026/01/13/1001/GOOGL.parquet`
Rows: 1, Cols: 56
Schema:
| column | dtype | null_pct |
|---|---|---|
| Symbol | object | 0.0 |
| AssetType | object | 0.0 |
| Name | object | 0.0 |
| Description | object | 0.0 |
| CIK | object | 0.0 |
| Exchange | object | 0.0 |
| Currency | object | 0.0 |
| Country | object | 0.0 |
| Sector | object | 0.0 |
| Industry | object | 0.0 |
| Address | object | 0.0 |
| OfficialSite | object | 0.0 |
| FiscalYearEnd | object | 0.0 |
| LatestQuarter | object | 0.0 |
| MarketCapitalization | object | 0.0 |
| EBITDA | object | 0.0 |
| PERatio | object | 0.0 |
| PEGRatio | object | 0.0 |
| BookValue | object | 0.0 |
| DividendPerShare | object | 0.0 |
| DividendYield | object | 0.0 |
| EPS | object | 0.0 |
| RevenuePerShareTTM | object | 0.0 |
| ProfitMargin | object | 0.0 |
| OperatingMarginTTM | object | 0.0 |
| ReturnOnAssetsTTM | object | 0.0 |
| ReturnOnEquityTTM | object | 0.0 |
| RevenueTTM | object | 0.0 |
| GrossProfitTTM | object | 0.0 |
| DilutedEPSTTM | object | 0.0 |
| QuarterlyEarningsGrowthYOY | object | 0.0 |
| QuarterlyRevenueGrowthYOY | object | 0.0 |
| AnalystTargetPrice | object | 0.0 |
| AnalystRatingStrongBuy | object | 0.0 |
| AnalystRatingBuy | object | 0.0 |
| AnalystRatingHold | object | 0.0 |
| AnalystRatingSell | object | 0.0 |
| AnalystRatingStrongSell | object | 0.0 |
| TrailingPE | object | 0.0 |
| ForwardPE | object | 0.0 |
| PriceToSalesRatioTTM | object | 0.0 |
| PriceToBookRatio | object | 0.0 |
| EVToRevenue | object | 0.0 |
| EVToEBITDA | object | 0.0 |
| Beta | object | 0.0 |
| 52WeekHigh | object | 0.0 |
| 52WeekLow | object | 0.0 |
| 50DayMovingAverage | object | 0.0 |
| 200DayMovingAverage | object | 0.0 |
| SharesOutstanding | object | 0.0 |
| SharesFloat | object | 0.0 |
| PercentInsiders | object | 0.0 |
| PercentInstitutions | object | 0.0 |
| DividendDate | object | 0.0 |
| ExDividendDate | object | 0.0 |
| source | object | 0.0 |

### Provider: finnhub
Example file: `data/raw/fundamentals/finnhub/GOOGL/2026/01/13/1001/GOOGL.parquet`
Rows: 1, Cols: 132
Schema:
| column | dtype | null_pct |
|---|---|---|
| 10DayAverageTradingVolume | float64 | 0.0 |
| 13WeekPriceReturnDaily | float64 | 0.0 |
| 26WeekPriceReturnDaily | float64 | 0.0 |
| 3MonthADReturnStd | float64 | 0.0 |
| 3MonthAverageTradingVolume | float64 | 0.0 |
| 52WeekHigh | float64 | 0.0 |
| 52WeekHighDate | object | 0.0 |
| 52WeekLow | float64 | 0.0 |
| 52WeekLowDate | object | 0.0 |
| 52WeekPriceReturnDaily | float64 | 0.0 |
| 5DayPriceReturnDaily | float64 | 0.0 |
| assetTurnoverAnnual | float64 | 0.0 |
| assetTurnoverTTM | float64 | 0.0 |
| beta | float64 | 0.0 |
| bookValuePerShareAnnual | float64 | 0.0 |
| bookValuePerShareQuarterly | float64 | 0.0 |
| bookValueShareGrowth5Y | float64 | 0.0 |
| capexCagr5Y | float64 | 0.0 |
| cashFlowPerShareAnnual | float64 | 0.0 |
| cashFlowPerShareQuarterly | float64 | 0.0 |
| cashFlowPerShareTTM | float64 | 0.0 |
| cashPerSharePerShareAnnual | float64 | 0.0 |
| cashPerSharePerShareQuarterly | float64 | 0.0 |
| currentDividendYieldTTM | float64 | 0.0 |
| currentEv/freeCashFlowAnnual | float64 | 0.0 |
| currentEv/freeCashFlowTTM | float64 | 0.0 |
| currentRatioAnnual | float64 | 0.0 |
| currentRatioQuarterly | float64 | 0.0 |
| dividendIndicatedAnnual | float64 | 0.0 |
| dividendPerShareAnnual | float64 | 0.0 |
| dividendPerShareTTM | float64 | 0.0 |
| dividendYieldIndicatedAnnual | float64 | 0.0 |
| ebitdPerShareAnnual | float64 | 0.0 |
| ebitdPerShareTTM | float64 | 0.0 |
| ebitdaCagr5Y | float64 | 0.0 |
| ebitdaInterimCagr5Y | float64 | 0.0 |
| enterpriseValue | int64 | 0.0 |
| epsAnnual | float64 | 0.0 |
| epsBasicExclExtraItemsAnnual | float64 | 0.0 |
| epsBasicExclExtraItemsTTM | float64 | 0.0 |
| epsExclExtraItemsAnnual | float64 | 0.0 |
| epsExclExtraItemsTTM | float64 | 0.0 |
| epsGrowth3Y | float64 | 0.0 |
| epsGrowth5Y | float64 | 0.0 |
| epsGrowthQuarterlyYoy | float64 | 0.0 |
| epsGrowthTTMYoy | float64 | 0.0 |
| epsInclExtraItemsAnnual | float64 | 0.0 |
| epsInclExtraItemsTTM | float64 | 0.0 |
| epsNormalizedAnnual | float64 | 0.0 |
| epsTTM | float64 | 0.0 |
| evEbitdaTTM | float64 | 0.0 |
| evRevenueTTM | float64 | 0.0 |
| focfCagr5Y | float64 | 0.0 |
| forwardPE | float64 | 0.0 |
| grossMargin5Y | float64 | 0.0 |
| grossMarginAnnual | float64 | 0.0 |
| grossMarginTTM | float64 | 0.0 |
| inventoryTurnoverAnnual | float64 | 0.0 |
| inventoryTurnoverTTM | float64 | 0.0 |
| longTermDebt/equityAnnual | float64 | 0.0 |
| longTermDebt/equityQuarterly | float64 | 0.0 |
| marketCapitalization | int64 | 0.0 |
| monthToDatePriceReturnDaily | float64 | 0.0 |
| netIncomeEmployeeAnnual | float64 | 0.0 |
| netIncomeEmployeeTTM | float64 | 0.0 |
| netInterestCoverageAnnual | float64 | 0.0 |
| netInterestCoverageTTM | float64 | 0.0 |
| netMarginGrowth5Y | float64 | 0.0 |
| netProfitMargin5Y | float64 | 0.0 |
| netProfitMarginAnnual | float64 | 0.0 |
| netProfitMarginTTM | float64 | 0.0 |
| operatingMargin5Y | float64 | 0.0 |
| operatingMarginAnnual | float64 | 0.0 |
| operatingMarginTTM | float64 | 0.0 |
| payoutRatioAnnual | float64 | 0.0 |
| payoutRatioTTM | float64 | 0.0 |
| pb | float64 | 0.0 |
| pbAnnual | float64 | 0.0 |
| pbQuarterly | float64 | 0.0 |
| pcfShareAnnual | float64 | 0.0 |
| pcfShareTTM | float64 | 0.0 |
| peAnnual | float64 | 0.0 |
| peBasicExclExtraTTM | float64 | 0.0 |
| peExclExtraAnnual | float64 | 0.0 |
| peExclExtraTTM | float64 | 0.0 |
| peInclExtraTTM | float64 | 0.0 |
| peNormalizedAnnual | float64 | 0.0 |
| peTTM | float64 | 0.0 |
| pegTTM | float64 | 0.0 |
| pfcfShareAnnual | float64 | 0.0 |
| pfcfShareTTM | float64 | 0.0 |
| pretaxMargin5Y | float64 | 0.0 |
| pretaxMarginAnnual | float64 | 0.0 |
| pretaxMarginTTM | float64 | 0.0 |
| priceRelativeToS&P50013Week | float64 | 0.0 |
| priceRelativeToS&P50026Week | float64 | 0.0 |
| priceRelativeToS&P5004Week | float64 | 0.0 |
| priceRelativeToS&P50052Week | float64 | 0.0 |
| priceRelativeToS&P500Ytd | float64 | 0.0 |
| psAnnual | float64 | 0.0 |
| psTTM | float64 | 0.0 |
| ptbvAnnual | float64 | 0.0 |
| ptbvQuarterly | float64 | 0.0 |
| quickRatioAnnual | float64 | 0.0 |
| quickRatioQuarterly | float64 | 0.0 |
| receivablesTurnoverAnnual | float64 | 0.0 |
| receivablesTurnoverTTM | float64 | 0.0 |
| revenueEmployeeAnnual | float64 | 0.0 |
| revenueEmployeeTTM | float64 | 0.0 |
| revenueGrowth3Y | float64 | 0.0 |
| revenueGrowth5Y | float64 | 0.0 |
| revenueGrowthQuarterlyYoy | float64 | 0.0 |
| revenueGrowthTTMYoy | float64 | 0.0 |
| revenuePerShareAnnual | float64 | 0.0 |
| revenuePerShareTTM | float64 | 0.0 |
| revenueShareGrowth5Y | float64 | 0.0 |
| roa5Y | float64 | 0.0 |
| roaRfy | float64 | 0.0 |
| roaTTM | float64 | 0.0 |
| roe5Y | float64 | 0.0 |
| roeRfy | float64 | 0.0 |
| roeTTM | int64 | 0.0 |
| roi5Y | float64 | 0.0 |
| roiAnnual | float64 | 0.0 |
| roiTTM | float64 | 0.0 |
| tangibleBookValuePerShareAnnual | float64 | 0.0 |
| tangibleBookValuePerShareQuarterly | float64 | 0.0 |
| tbvCagr5Y | float64 | 0.0 |
| totalDebt/totalEquityAnnual | float64 | 0.0 |
| totalDebt/totalEquityQuarterly | float64 | 0.0 |
| yearToDatePriceReturnDaily | float64 | 0.0 |
| source | object | 0.0 |

## 4. Sentiment - raw (representative)
Example file: `data/raw/sentiment/GOOGL/2026/01/13/1001/sentiment_GOOGL_newsapi.parquet`
Rows: 10, Cols: 4
Date coverage: 2026-01-11 14:00:07+00:00 -> 2026-01-13 23:52:09+00:00
Schema:
| column | dtype | null_pct |
|---|---|---|
| source | object | 0.0 |
| title | object | 0.0 |
| publishedAt | object | 0.0 |
| hash | object | 0.0 |

## 5. Processed / features samples (if present)
### processed_fundamentals
Example file: `data/processed/fundamentals/2026/01/13/1001/V.parquet`
Rows: 1, Cols: 16
Schema (first 60 columns if large):
| column | dtype | null_pct |
|---|---|---|
| ticker | string | 0.0 |
| pe_ratio | Float64 | 0.0 |
| pb_ratio | Float64 | 0.0 |
| roe | Float64 | 0.0 |
| roa | Float64 | 0.0 |
| de_ratio | Float64 | 0.0 |
| dividend_yield | Float64 | 0.0 |
| eps | Float64 | 0.0 |
| shares_outstanding | string | 0.0 |
| percent_institutions | string | 0.0 |
| percent_insiders | string | 0.0 |
| gross_margin | Float64 | 0.0 |
| operating_margin | Float64 | 0.0 |
| net_margin | object | 100.0 |
| free_cash_flow | object | 100.0 |
| ytd_return | Float64 | 0.0 |

### processed_daily_prices
Example file: `data/processed_daily/prices_daily.parquet`
Rows: 500, Cols: 6
Schema (first 60 columns if large):
| column | dtype | null_pct |
|---|---|---|
| open | float64 | 0.0 |
| high | float64 | 0.0 |
| low | float64 | 0.0 |
| close | float64 | 0.0 |
| volume | float64 | 0.0 |
| ticker | object | 0.0 |

### processed_daily_fundamentals
Example file: `data/processed_daily/fundamentals_daily.parquet`
Rows: 26, Cols: 16
Schema (first 60 columns if large):
| column | dtype | null_pct |
|---|---|---|
| ticker | object | 0.0 |
| pe_ratio | Float64 | 0.0 |
| pb_ratio | Float64 | 0.0 |
| roe | Float64 | 0.0 |
| roa | Float64 | 0.0 |
| de_ratio | Float64 | 0.0 |
| dividend_yield | Float64 | 23.077 |
| eps | Float64 | 0.0 |
| shares_outstanding | string | 0.0 |
| percent_institutions | string | 0.0 |
| percent_insiders | string | 0.0 |
| gross_margin | Float64 | 15.385 |
| operating_margin | Float64 | 0.0 |
| net_margin | object | 100.0 |
| free_cash_flow | object | 100.0 |
| ytd_return | Float64 | 0.0 |

### features_sample
Example file: `data/processed/features/2026/01/13/features.parquet`
Rows: 390, Cols: 44
Schema (first 60 columns if large):
| column | dtype | null_pct |
|---|---|---|
| open | float64 | 0.0 |
| high | float64 | 0.0 |
| low | float64 | 0.0 |
| close | float64 | 0.0 |
| volume | float64 | 0.0 |
| SMA_20 | float64 | 0.0 |
| EMA_20 | float64 | 0.0 |
| daily_return | float64 | 0.0 |
| volatility | float64 | 0.0 |
| volume_avg | float64 | 0.0 |
| RSI | float64 | 0.0 |
| MACD | float64 | 0.0 |
| MACD_signal | float64 | 0.0 |
| bollinger_upper | float64 | 0.0 |
| bollinger_lower | float64 | 0.0 |
| bollinger_width | float64 | 0.0 |
| ticker | object | 0.0 |
| pe_ratio | float64 | 0.0 |
| pb_ratio | float64 | 0.0 |
| roe | float64 | 0.0 |
| roa | float64 | 0.0 |
| de_ratio | float64 | 0.0 |
| dividend_yield | float64 | 40.0 |
| eps | float64 | 0.0 |
| shares_outstanding | int64 | 0.0 |
| percent_institutions | float64 | 0.0 |
| percent_insiders | float64 | 0.0 |
| gross_margin | float64 | 0.0 |
| operating_margin | float64 | 0.0 |
| net_margin | float64 | 100.0 |
| free_cash_flow | float64 | 100.0 |
| ytd_return | float64 | 0.0 |
| sentimiento_especifico | float64 | 0.0 |
| sentimiento_general | float64 | 0.0 |
| RSI_t-1 | float64 | 0.0 |
| daily_return_t-1 | float64 | 0.0 |
| MACD_t-1 | float64 | 0.0 |
| target_clasificacion | int64 | 0.0 |
| RSI_x_volume | float64 | 0.0 |
| MACD_x_sentimiento | float64 | 0.0 |
| target_regresion_t+1 | float64 | 0.0 |
| target_clasificacion_t+1 | int64 | 0.0 |
| timestamp_proceso | datetime64[us] | 0.0 |
| timestamp_ejecucion | datetime64[us] | 0.0 |

## 6. Cross-provider reconciliation
- Prices (stooq vs alphaV) have different layouts: stooq includes a `date` column and `ticker` column; alphaV uses a DatetimeIndex and no `ticker` column.
- AlphaV price files are stored under `data/raw/prices/alphaV/...`, while stooq files are stored under `data/raw/prices/<TICKER>/...` (provider implicit).
- Fundamentals providers have different schemas and data types; alphaV is mostly string-typed, finnhub mostly numeric floats.

## 7. Recommendations
- Normalize raw prices into a single canonical layout: `data/raw/prices/<provider>/<ticker>/YYYY/MM/DD/HHMM/` with a `date` column and `ticker` column. Add `provider` column on write if needed.
- Normalize alphaV price index to a `date` column so downstream joins do not rely on index semantics.
- Normalize alphaV fundamentals numeric fields to floats before merging with finnhub metrics.
- Define a minimal normalized contract for raw fundamentals (one row per ticker per run with numeric dtypes) and write it to `data/processed/fundamentals` only.
