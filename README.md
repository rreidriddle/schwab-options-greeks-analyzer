# Black-Scholes Greeks Dashboard

A Python tool that uses Schwab API data to fetch live options chain data
and compute second-order greeks for S&P 500 ticker SPY. It visualizes current
GammaEX, VannaEX, and CharmEX for market maker hedging flows.

![Options Greeks Dashboard](dashboard.png)

---

## What It Does

- Auth.py walks you through Charles Schwab's authentication process
- Fetches full options chain across near spot strikes and expirations for SPY
    - Delta, Vega (first-order)
    - Gamma, Vanna, Charm (second-order)
- Measures both call and put greeks with a net toggle option
- Aggregates net dealer exposure by strike across all expirations, scaled by
    open interest and the options multiplier
- Renders a multi-panel dashboard showing GammaEX, VannaEX, and CharmEX
    for three ETFs

| Greek | Order | What It Tells You |
|-------|-------|-------------------|
| **Gamma (GEX)** | 2nd | How dealer delta changes per $1 move — positive GEX stabilizes price, negative GEX amplifies moves |
| **Vanna (VannEX)** | 2nd | How dealer delta changes when IV moves — drives mechanical flows after VIX spikes/drops |
| **Charm (CharmEX)** | 2nd | How dealer delta changes as time passes — creates predictable intraday drift even with no price move |

### Why This Matters for Markets

When dealers are in a negative gamma regime (GEX < 0), they're hedging
with the market. This causes dealers to amplify the current trend. GEX exposes
the strikes that dealers are positioned the heaviest. These levels can act as
strong support or resistance.

Vanna Exposure charts the sensitivity of dealer delta hedges to changes in implied
volatility. When IV moves dealers are forced to buy or sell the underlying to hedge.
The direction and magnitude of those flows can be found in the vanna profile before
the move ever happens.

Charm represents delta decay. As dealers' delta decays from options they have sold,
they must buy or sell shares to rebalance their hedge. Charm gives us an idea of those
guaranteed flows as expirations get closer.

---

## Modules

### GEX / VannEX / CharmEX (Charts)
The main module. Displays a horizontal bar chart of Gamma Exposure by strike alongside
Vanna and Charm exposure curves. Key levels such as spot price, gamma flip, and max pain
are overlaid on the GEX chart. Use the control bar to filter by DTE, expiration date,
and strike range, or toggle Vanna and Charm between net and call/put split views.

### 


### Macro

**Regime Badge**
At the top of the panel sits a color-coded macro regime badge. This badge synthesizes
bond market health, energy prices, and options positioning into a single actionable
label updated every ten minutes by the collector. Four regime states are possible:

| Regime | Color | What It Means |
|--------|-------|---------------|
| GREEN | 🟢 | Bond market stable, oil contained, macro tailwind for equities |
| YELLOW | 🟡 | Early warning signs present — reduce conviction, wait for confirmation |
| ORANGE | 🟠 | Meaningful macro headwind — yields rising, oil elevated, or bonds deteriorating |
| RED | 🔴 | Danger zone breach — 30-year yield above 5%, oil significantly elevated, or bonds near 52-week lows |

Signals shown are a combination of macro regime and GEX/VEX/CEX regime. We can combine
the two to determine whether they are working together or inversely. This also shows us
if there is an edge at all. If not, reduce size or wait for confirmation. 

**Yield Curve**
Below the regime badge, the U.S. Treasury yield curve is plotted.
Today's curve is shown as a solid line.Yesterday's curve is shown as a faint
ghost line behind it, making the daily shift immediately visible at a glance.

A normal curve slopes upward: short-term rates lower than long-term rates, meaning 
markets expect stable growth and moderate inflation. An inverted curve, where short-term
rates exceed long-term rates, has historically preceded recessions. A flat curve
signals uncertainty about the economic path ahead.

Two key spreads are always annotated on the chart:
- **10Y-2Y Spread** — the most watched recession indicator. When this goes negative (inverts) it turns red.
- **10Y-3M Spread** — a complementary recession signal that often leads the 10Y-2Y.

A red dashed horizontal line marks the **5% threshold** on the 30-year yield.
This level is significant because above it, U.S. Treasury bonds offer a
near risk-free return competitive enough to draw capital away from equities,
increasing pressure on stock valuations.

**Data Table**
A compact table sits directly below the yield curve showing:
- Each maturity's current yield and its change from the prior day (green = fell, red = rose)
- Both key spreads with inversion warnings
- Live readings for TLT (long-term bond ETF), USO (oil proxy), TNX (10-year yield), and TYX (30-year yield)

**IV Skew**
At the bottom of the panel, the implied volatility smile plots call IV and put IV
across strikes for the selected expiration. The shape of this curve reveals where
the market is pricing risk. A classic volatility skew is asymmetric: OTM puts
carry higher IV than equidistant OTM calls driven by demand for downside
protection. A volatility smile is more symmetric, with IV lowest at-the-money,
indicating the market is pricing the possibility of a large move in either direction.
This connects directly to the VannEX chart: a steeper skew means higher vanna
sensitivity and stronger mechanical hedging flows when IV moves.

> **Note:** The Macro tab requires the collector to be running to populate the
> regime badge, yield curve, and data table. The Vol Smile section renders from
> live chain data and is always available. See
> [schwab-greeks-historical-data](https://github.com/rreidriddle/schwab-greeks-historical-data)
> for the data collection pipeline.


### Backtest
Using the calendar widget, you can select any historical date to visualize that day's
opening GEX snapshot alongside its full open-to-close price action. This allows you to
study how price moved relative to key GEX levels: call walls, put walls, the gamma flip,
and max pain. This graphs how dealer positioning influenced intraday structure.
The backtest module reads from greeks_history.db via db.py, a read-only database access
layer produced by the schwab-greeks-historical-data collection tool.

> **Note:** This repo contains only the dashboard framework. A historical greeks database is
> required to populate the backtest. See
> [schwab-greeks-historical-data](https://github.com/rreidriddle/schwab-greeks-historical-data)
> for the data collection and storage pipeline.

---

## Project Structure

```
black-scholes-greeks-dashboard/
├── gex-dashboard.py             # Main script — Greeks engine + API + dashboard
├── requirements.txt             # Python dependencies
├── .env                         # API credentials (not tracked by Git)
├── .gitignore                   # Protects credentials and cache files
├── README.md                    # This file
└── auth.py                      # Authenticator for Schwab API
```

---

## Usage

### Demo Mode
No credentials required. Run the script with no `.env` file and it launches automatically
in demo mode using a synthetic SPY dataset modelled on real market structure:

```bash
python gex-dashboard.py
```

The demo runs the full Greeks engine on simulated options chain data — same Black-Scholes
calculations as live mode, with realistic OI distribution, volatility skew, and key levels.
The BACKTEST module requires live mode and will display a message if accessed in demo.

### Live Mode
Add your Schwab API credentials to a `.env` file in the project root:

```
SCHWAB_CLIENT_ID=your_client_id
SCHWAB_CLIENT_SECRET=your_client_secret
```

Run `auth.py` first to complete Schwab's OAuth flow and cache your access token, then:

```bash
python gex-dashboard.py
```

Live mode fetches real-time options chains for SPY auto-refreshing
every 5 minutes. A status indicator in the control bar shows refresh state.

---

## Installation

**Prerequisites**
- Python 3.12+
- Charles Schwab API credentials (see[developer.schwab.com](https://developer.schwab.com))

**Clone the repo and install dependencies**
```bash
git clone https://github.com/rreidriddle/black-scholes-greeks-dashboard.git
cd black-scholes-greeks-dashboard
pip install -r requirements.txt
```

**Set up credentials**

Create a `.env` file in the project root:
```
SCHWAB_CLIENT_ID=your_client_id
SCHWAB_CLIENT_SECRET=your_client_secret
```

**Authenticate**

Run `auth.py` once to complete Schwab's OAuth flow and cache your access token:
```bash
python auth.py
```
You will be prompted to log in via browser. Once complete, your token is cached locally
and the dashboard will auto-refresh it as needed.

**Run**
```bash
python gex-dashboard.py
```

## Sample Output — Console Summary

```
══════════════════════════════════════════════════════════
  SPY  |  Spot $679.66  |  OI 4,245,570
══════════════════════════════════════════════════════════
  Net GEX     $+0.531B  POSITIVE
  Net VannEX  $+253270K
  Net CharmEX -2.4584M

```
