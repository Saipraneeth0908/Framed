# Motorsport Gallery

A Flask storefront concept for configurable framed automotive posters. Visitors can browse and filter the collection, configure a frame, size, and visual theme, save designs locally, preview a poster on a room photo, and build a discounted set.

## Requirements

- Python 3.11 or newer

## Local setup (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Open <http://127.0.0.1:5000>.

For development checks:

```powershell
python -m pip install -r requirements-dev.txt
ruff check .
ruff format --check .
pytest
```

## Configuration

Set `FLASK_SECRET_KEY` to a long random value outside local development. Copy `.env.example` only as a reference; Flask does not automatically load `.env` in this project.

## Current limitations

- Checkout is a demonstration and does not take payment.
- Contact and newsletter forms do not send or persist data.
- Product data is stored in `data/products.json`; there is no database.
- Most referenced poster/gallery/360-degree images have not yet been added. The interface provides visual fallbacks where possible.
