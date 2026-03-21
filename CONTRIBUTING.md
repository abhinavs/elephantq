# Contributing to ElephantQ

Thanks for contributing. ElephantQ is a **single package** with optional extras for advanced features.

## Project Structure

- `elephantq/` — core runtime
- `elephantq/dashboard/` — web UI (optional, opt-in)
- `elephantq/features/` — scheduling, recurring, metrics, logging, webhooks, dead-letter, security (optional, opt-in)

## Getting Started

```bash
git clone https://github.com/abhinavs/elephantq.git
cd elephantq

python -m venv venv
source venv/bin/activate

pip install -e ".[dev]"
```

Optional extras:

```bash
pip install -e ".[dev,dashboard]"
pip install -e ".[dev,monitoring]"
```

## Database Setup

Create a test database and set the connection string:

```bash
createdb elephantq_test
export ELEPHANTQ_DATABASE_URL="postgresql://localhost/elephantq_test"
```

Run migrations:

```bash
python -c "
import asyncio
from elephantq.db.migrations import run_migrations
asyncio.run(run_migrations())
"
```

## Running Tests

Unit tests (no database needed):

```bash
python -m pytest tests/unit/ -v
```

Integration tests (requires the test database above):

```bash
python -m pytest tests/integration/ -v
```

Full suite:

```bash
python -m pytest tests/ -v
```

## Coding Standards

- Use async/await consistently
- Add type hints for public APIs
- Keep error messages actionable
- Add tests for new behavior
