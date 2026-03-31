# Schwab Options Greeks Analyzer

A Python tool that connects to the **Charles Schwab MarketData API** to fetch
live options chain data and compute second-order Greeks for **SPY, QQQ, and DIA**
— visualizing net dealer exposure profiles across strikes to model how market
maker hedging flows affect underlying price action.

![Options Greeks Dashboard](dashboard.png)

---

## Background & Motivation

Modern equity markets are heavily influenced by the mechanical hedging activity
of options market makers. Understanding **Gamma Exposure (GEX)**, **Vanna**, and
**Charm** allows analysts to anticipate structural price flows that aren't driven
by fundamental news — flows that are purely the result of dealer risk management.

This project was built to bridge my finance education with practical Python
development — moving away from Excel-based workflows toward a fully programmatic
data pipeline that can scale, automate, and visualize complex derivatives data
in real time.

As a finance student pursuing the CFA and targeting trading desk and financial
data analyst roles, I wanted to build something that reflects how professional
desks actually think about options positioning — not just textbook Greeks, but
the second-order cross-sensitivities that drive intraday market structure.

---

## What It Does

- Authenticates with the **Charles Schwab MarketData API** via OAuth2
- Fetches full options chains across all strikes and expirations for SPY, QQQ, DIA
- Computes **first and second-order Greeks** analytically using Black-Scholes:
  - Delta, Vega (first-order)
  - Gamma, Vanna, Charm, Vomma, Speed, Color (second-order)
- **Sign-adjusts for dealer perspective** — calls and puts are treated correctly
  to reflect how market makers are actually positioned
- **Aggregates net dealer exposure by strike** across all expirations, scaled
  by open interest and the options multiplier
- Identifies key structural levels: **gamma flip point**, call walls, put walls
- Renders a **multi-panel dashboard** showing GEX, VannEX, CharmEX, and VommEX
  profiles for all three ETFs simultaneously

---

## The Greeks — What They Measure

| Greek | Order | What It Tells You |
|-------|-------|-------------------|
| **Gamma (GEX)** | 2nd | How dealer delta changes per $1 move — positive GEX stabilizes price, negative GEX amplifies moves |
| **Vanna (VannEX)** | 2nd cross | How dealer delta changes when IV moves — drives mechanical flows after VIX spikes/drops |
| **Charm (CharmEX)** | 2nd cross | How dealer delta changes as time passes — creates predictable intraday drift even with no price move |
| **Vomma (VommEX)** | 2nd | How vega changes with IV — measures convexity of volatility exposure |
| **Speed** | 3rd | How gamma changes per $1 move — gamma of gamma |
| **Color** | 3rd | How gamma changes per day — gamma decay |

### Why This Matters for Markets

When dealers are in a **negative gamma** regime (GEX < 0), their hedging
amplifies every move — small sell-offs become waterfalls, small rallies get
squeezed. This is the environment that produces the violent, headline-driven
swings seen during macro uncertainty.

**Vanna** is particularly powerful around macro events. When VIX spikes and
traders pile into puts, dealers accumulate large short hedges. When volatility
mean-reverts — even without a fundamental catalyst — dealers mechanically unwind
those hedges, creating the "low-volume melt-up" pattern experienced traders
recognize immediately.

**Charm** creates predictable end-of-day flows. As options approach expiration,
delta bleeds away from puts and calls, forcing dealers to re-hedge even if price
hasn't moved — producing the gravitational pull toward key strikes seen on
expiration Fridays.

---

## Tech Stack

- **Python 3.11+**
- **Charles Schwab MarketData API** — live options chain data via OAuth2
- **Black-Scholes model** — analytical Greek calculations (no external pricing library)
- **pandas** — data manipulation and aggregation
- **numpy / scipy** — mathematical computations and normal distribution functions
- **matplotlib** — multi-panel dashboard visualization

---

## Project Structure

```
schwab-options-greeks-analyzer/
├── options_greeks_analyzer.py   # Main script — Greeks engine + API + dashboard
├── requirements.txt             # Python dependencies
├── .env                         # API credentials (not tracked by Git)
├── .gitignore                   # Protects credentials and cache files
└── README.md                    # This file
```

---

## Setup & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/rreidriddle/schwab-options-greeks-analyzer.git
cd schwab-options-greeks-analyzer
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Get Schwab API Credentials
- Register an account at [developer.schwab.com](https://developer.schwab.com)
- Create a new app to receive your **App Key** (Client ID) and **Secret**
- Set the redirect URI to `https://127.0.0.1`

### 4. Configure Your .env File
Create a `.env` file in the project root:
```env
SCHWAB_CLIENT_ID=your_app_key_here
SCHWAB_CLIENT_SECRET=your_secret_here
SCHWAB_REDIRECT_URI=https://127.0.0.1
```

### 5. Run the Analyzer
```bash
python options_greeks_analyzer.py
```

---

## Demo Mode

No Schwab credentials? Run the script as-is — it automatically falls back to
**demo mode**, generating synthetic options data modeled on a high-volatility,
geopolitical-risk market environment. All Greeks calculations and the full
dashboard render exactly as they would with live data.

```bash
# No .env needed — demo mode activates automatically
python options_greeks_analyzer.py
```

---

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

---

## Reading the Dashboard

**Horizontal bars** represent net dealer exposure at each strike price.
Green bars = positive exposure (stabilizing), red bars = negative (amplifying).

**The dashed white line** marks the current spot price.

**The dotted yellow line** marks the **gamma flip level** — the price at which
aggregate dealer behavior switches from stabilizing to amplifying. This is the
single most important structural level in the options market.

**Above the gamma flip:** dealers buy dips and sell rips — price is contained.
**Below the gamma flip:** dealers sell dips and buy rips — moves accelerate.

---

## What I Learned Building This

- How to authenticate with a production financial API using OAuth2
- Translating mathematical derivatives formulas directly into Python functions
- The difference between first-order and second-order options Greeks and why
  the higher-order ones drive more predictable market structure than delta alone
- How to structure a data pipeline from raw API response → parsed DataFrame →
  aggregated exposure → visualization
- Git version control and professional project organization for collaborative
  and portfolio-facing codebases

---

## Roadmap

- [ ] Complete Schwab OAuth2 browser-based authentication flow
- [ ] Add 0DTE specific exposure tracking (SPY trades millions of 0DTE contracts daily)
- [ ] Intraday GEX updates on a timer loop
- [ ] Add max pain calculation by expiration
- [ ] Export exposure data to CSV for further analysis
- [ ] Expand to individual equities beyond index ETFs

---

## Author

**Reid Riddle**
Finance Student | CFA Candidate | Aspiring Trading Desk & Financial Data Analyst

- GitHub: [@rreidriddle](https://github.com/rreidriddle)
- LinkedIn: (https://www.linkedin.com/in/rreidriddle/)

---

*This project is for educational and portfolio purposes.
Nothing here constitutes financial advice.*
