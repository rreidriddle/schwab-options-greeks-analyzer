# Black-Scholes Greeks Dashboard

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
    open interest and the options multiplier
- Renders a multi-panel dashboard showing GammaEX, VannaEX, and CharmEX
    for three ETFs. 

| Greek | Order | What It Tells You |
|-------|-------|-------------------|
| **Gamma (GEX)** | 2nd | How dealer delta changes per $1 move - positive GEX stabilizes price, negative GEX amplifies moves |
| **Vanna (VannEX)** | 2nd | How dealer delta changes when IV moves drives mechanical flows after VIX spikes/drops |
| **Charm (CharmEX)** | 2nd | How dealer delta changes as time passes creates predictable intraday drift even with no price move |
| **Vomma (VommEX)** | 2nd | How vega changes with IV, measures convexity of volatility exposure |
| **Speed** | 3rd | How gamma changes per $1 move: gamma of gamma |
| **Color** | 3rd | How gamma changes per day: gamma decay |

### Why This Matters for Markets

When dealers are in a negative gamma regime (GEX < 0), they're hedging
with the market. This causes dealers to amplify the current trend. GEX exposes
the strikes that dealers are positioned the heaviest. These levels can act as
strong support or resistance.

Vanna Exposure charts the sensitivity of dealer delta hedges to changes in implied
volatility. When IV moves dealers are forced to buy or sell the underlying to hedge.
The direction and magnitude of those flows can be found in the vanna profile before
the move ever happens.

Charm represents delta decay, as dealers delta decays from options they have sold
they must buy or sell shares to hedge. Charm gives us an idea of those guaranteed
flows as expirations get closer. 

## Project Structure

```
black-scholes-greeks-dashboard/
├── gex-dashboard.py   # Main script — Greeks engine + API + dashboard
├── requirements.txt             # Python dependencies
├── .env                         # API credentials (not tracked by Git)
├── .gitignore                   # Protects credentials and cache files
├── README.md                    # This file
└── auth.py                      # Authenticator for Schwab API
```
## Sample Output — Console Summary

```
SPY...
  $652.24

══════════════════════════════════════════════════════════
  SPY  |  Spot $652.24  |  OI 5,744,260
══════════════════════════════════════════════════════════
  Net GEX     $-0.954B  NEGATIVE
  Net VannEX  $+262.6M
  Net CharmEX -4404.4K

QQQ...
  $580.19

══════════════════════════════════════════════════════════
  QQQ  |  Spot $580.19  |  OI 2,690,690
══════════════════════════════════════════════════════════
  Net GEX     $-0.096B  NEGATIVE
  Net VannEX  $+92.4M
  Net CharmEX -1508.6K

DIA...
  $463.76

══════════════════════════════════════════════════════════
  DIA  |  Spot $463.76  |  OI 86,449
══════════════════════════════════════════════════════════
  Net GEX     $+0.001B  POSITIVE
  Net VannEX  $+4.1M
  Net CharmEX -60.4K

```

## Author

**Reid Riddle**

- GitHub: [@rreidriddle](https://github.com/rreidriddle)
- LinkedIn: (https://www.linkedin.com/in/rreidriddle/)
