# KJA Digital Twin System

Precision aquaculture digital twin proof-of-concept for small-scale floating net cage (KJA) fish farming in Tanjungpinang, Indonesia.

## Tech Stack

- **Backend:** Python 3.12, Flask (REST API + serves Vue static build)
- **Frontend:** Vue 3 (Composition API), PrimeVue 4 (Aura dark theme)
- **Database:** SQLite via SQLAlchemy
- **ML:** TFT inference stub (`neuralforecast` integration planned)
- **Target deployment:** Raspberry Pi 4 (ARM64, 4GB RAM)

## Project Structure

```
kja-system/
├── app.py                 # Flask entry point
├── config.py              # Dev/prod configuration
├── requirements.txt
├── database/              # SQLAlchemy models + seed script
├── api/                   # REST API blueprints
├── inference/             # TFT model stub
├── frontend/              # Vue 3 + Vite dev server
└── static/                # Vue production build output
```

## Prerequisites

- Python 3.12+
- Node.js 18+ and npm

## Setup

### 1. Python virtual environment

```bash
python3 -m venv venv
```

Activate the virtual environment:

- **macOS/Linux:** `source venv/bin/activate`
- **Windows:** `venv\Scripts\activate`

All Python packages must be installed inside this venv (never globally).

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Seed the database

```bash
python database/seed.py
```

This creates 4 KJA units with 7 days of hourly simulated sensor data (168 readings per unit).

### 4. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

## Development

Run Flask and the Vite dev server in **two separate terminals** (both with venv activated for Flask):

**Terminal 1 — Flask API (port 5000):**

```bash
source venv/bin/activate   # macOS/Linux
flask --app app run --port 5000 --debug
```

**Terminal 2 — Vue dev server (port 5173):**

```bash
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser. Vite proxies `/api` requests to Flask at `http://localhost:5000`.

## Production Build

Build the Vue frontend into `/static` and serve everything from Flask:

```bash
cd frontend
npm run build
cd ..
source venv/bin/activate
flask --app app run --host 0.0.0.0 --port 5000
```

Open **http://localhost:5000**.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sensor/latest` | Latest reading per KJA unit |
| GET | `/api/sensor/history/<kja_id>?hours=24` | Time-series sensor data |
| GET | `/api/kja/units` | List all KJA units and status |
| GET | `/api/alert/list` | Recent alerts |
| POST | `/api/alert/read/<id>` | Mark alert as read |
| GET | `/api/inference/do/<kja_id>` | TFT DO prediction (stub) |
| GET | `/api/health` | Health check |

## Demo Scenarios

- **KJA-03:** Declining dissolved oxygen trend (critical alert demo)
- **All units:** Slightly low salinity (monsoon season scenario)
- **TFT badge:** DO values shown with model prediction indicator

## Sensor Thresholds (Grouper / Kerapu)

| Parameter | Normal | Perhatian | Kritis |
|-----------|--------|-----------|--------|
| pH | 7.5–8.5 | <7.3 or >8.7 | <7.0 or >9.0 |
| Suhu | 26–30°C | <24 or >31 | <22 or >33 |
| Salinitas | 28–34 ppt | 24–28 or >34 | <22 |
| Turbiditas | <15 NTU | 15–30 | >30 |
| DO (prediksi) | ≥5 mg/L | 4–5 | <4 |

## License

PhD research proof-of-concept — internal use.
