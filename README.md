new readme

# Schwab Options Greek Analyzer

A Python tool that uses Schwab API data to fetch live options chain data
and compute second-order greeks for SPY, QQQ, and DIA. It visualizes current
GammaEX, VannaEX, and CharmEX for market maker hedging flows.

![Options Greeks Dashboard](dashboard.png)


---

## What It Does

- Auth.py walks you through Charles Schwab's authentication process
- Fetches full options chain across near spot strikes and expirations for SPY, QQQ, DIA
- Computes first and second-order Greeks using Black-Scholes:
    - Delta, Vega (first-order)
    - Gamma, Vanna, Charm (second-order)
- Measures both call and put greeks with a net toggle option
- Aggregates net dealer exposure by strike across all expirations, scaled by
    by open interest and the options multiplier
- Renders a multi-panel dashboard showing GammaEX, VannaEX, and CharmEX
    for all three ETFs. 

| Greek | Order | What It Tells You |
|-------|-------|-------------------|
| **Gamma (GEX)** | 2nd | How dealer delta changes per $1 move - positive GEX stabilizes price, negative GEX amplifies moves |
| **Vanna (VannEX)** | 2nd | How dealer delta changes when IV moves drives mechanical flows after VIX spikes/drops |
| **Charm (CharmEX)** | 2nd | How dealer delta changes as time passes creates predictable intraday drift even with no price move |
| **Vomma (VommEX)** | 2nd | How vega changes with IV, measures convexity of volatility exposure |
| **Speed** | 3rd | How gamma changes per $1 move: gamma of gamma |
| **Color** | 3rd | How gamma changes per day: gamma decay |

### Why This Matters for Markets

When dealers are in a negative gamma regime (GEX < 0), their hedging
amplifies every move — small sell-offs become waterfalls, small rallies get
squeezed. This is the environment that produces the violent, headline-driven
swings seen during macro uncertainty.

Vanna is particularly powerful around macro events. When VIX spikes and
traders pile into puts, dealers accumulate large short hedges. When volatility
mean-reverts — even without a fundamental catalyst — dealers mechanically unwind
those hedges, creating the "low-volume melt-up" pattern experienced traders
recognize immediately.

Charm creates predictable end-of-day flows. As options approach expiration,
delta bleeds away from puts and calls, forcing dealers to re-hedge even if price
hasn't moved — producing the gravitational pull toward key strikes seen on
expiration Fridays.

## Project Structure

```
schwab-options-greeks-analyzer/
├── options_greeks_analyzer.py   # Main script — Greeks engine + API + dashboard
├── requirements.txt             # Python dependencies
├── .env                         # API credentials (not tracked by Git)
├── .gitignore                   # Protects credentials and cache files
└── README.md                    # This file
```
## Sample Output — Console Summary

```
════════════════════════════════════════════════════════════
  SPY  |  Spot: $632.14  |  Total OI: 2,309,964
════════════════════════════════════════════════════════════
  Net GEX    : $-0.233B  →  NEGATIVE (amplifying)
  Net VannEX : $-579.08M  →  BULLISH unwind risk
  Net CharmEX: +0.0189M  →  BEARISH delta bleed
  Net VommEX : $-1078.76M

  Top 5 strikes by |GEX|:
    $  639.0  -████████████████████  GEX=-19.3M  VannEX=-510.34M
    $  632.7  -███████████████████   GEX=-19.3M  VannEX=-21.24M
    $  635.9  -███████████████████   GEX=-18.4M  VannEX=-232.10M
```

## Author

**Reid Riddle**

- GitHub: [@rreidriddle](https://github.com/rreidriddle)
- LinkedIn: (https://www.linkedin.com/in/rreidriddle/)
