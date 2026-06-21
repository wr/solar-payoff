# Solar Payoff

A self-hosted dashboard that tracks how close your home solar system is to paying for itself. It pulls daily production from your Enphase system, values it against your electricity rate, and shows cumulative savings, a projected breakeven date, and a set of solar stats.

![dashboard screenshot](docs/screenshot.png)

## What you get

- **% paid off** and a projected **breakeven date** / payoff period
- Cumulative-savings chart climbing toward your install cost
- Monthly production, and a with-vs-without-solar bill chart
- Stats: yearly production, energy offset, performance vs. expected (PVWatts), clear-sky capture, CO₂ avoided
- Warranty countdown (panels / inverters / workmanship)
- A daily background sync from Enphase — set it up once and leave it

Everything is configured in the dashboard. Nothing about the system is hardcoded.

## How it works

1. **Production** comes from the Enphase Enlighten v4 API (daily, plus consumption if your system has CT meters). This is the part that just works for any Enphase user.
2. **Savings** = your production valued at your electricity rate. You enter a flat rate, or time-of-use rates with an on-peak window. The honest caveat: every utility prices power differently, so the payoff number is only as accurate as the rate you configure.
3. **Bills (optional)** — upload a Green Button export from your utility to fill in what you actually paid. Green Button is a US standard most utilities support.
4. **Performance (optional)** — enter your location and array tilt/azimuth and the dashboard fetches expected output from PVWatts to show how you're doing against the model.

## Quick start

You need [Docker](https://docs.docker.com/get-docker/) and a free Enphase developer app (below).

```bash
git clone <your-fork-url> solar-payoff
cd solar-payoff
cp .env.example .env        # add your Enphase app credentials
docker compose up -d --build
```

Open `http://localhost:8088` and walk the setup wizard.

### Get Enphase API credentials

1. Sign up at [developer-v4.enphase.com](https://developer-v4.enphase.com) and create an **App** on the free **Watt** plan.
2. Copy the **API key**, **Client ID**, and **Client Secret** into `.env`.
3. In the dashboard, click **Connect Enphase**, authorize, and paste the code it shows back. (One time; it syncs daily after that.)

### Then, in the dashboard

- Enter install cost, incentives, switch-on date, and your electricity rate.
- (Optional) Upload a Green Button export for real bill amounts.
- (Optional) Add your location + array tilt/azimuth and a free [NLR/PVWatts API key](https://developer.nlr.gov/signup/) to get the performance metric.

## Accuracy, honestly

Production is measured, so it's solid. The cost side is an estimate built from the rate you enter. Flat-rate utilities are straightforward. Time-of-use and net-metering rules vary a lot by state and utility — the closer you configure your tariff, the closer the payoff number. Upload Green Button to anchor it to real bills.

## Configuration

| Setting | Where | Notes |
|---|---|---|
| Enphase API key / client id / secret | `.env` | from your Enphase developer app |
| `PUBLIC_BASE_URL` | `.env` | optional; only for the one-click OAuth callback |
| Install cost, incentives, switch-on date | dashboard → Setup | |
| Electricity rate (flat or TOU) | dashboard → Setup | |
| Location, tilt, azimuth, NLR key | dashboard → Setup | for the PVWatts performance metric |
| Warranty terms | dashboard → Setup | defaults 25/25/25 years |

Data lives in a SQLite file under `./data` (gitignored). Back that up to keep your history.

## Tech

FastAPI + SQLite, a vanilla JS dashboard (Chart.js), one container. Daily sync via APScheduler. No build step.

## examples/

`examples/` holds custom integrations that aren't part of the default path — e.g. parsing a specific utility's statement PDFs out of a local mail client. They're reference, not required. Most people only need Green Button.

## License

MIT — see [LICENSE](LICENSE).
