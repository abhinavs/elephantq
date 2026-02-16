# Contributing to ElephantQ

Thanks for contributing. ElephantQ is a **single package** with optional extras for advanced features.

## Project Structure

- `elephantq/` — core runtime
- `elephantq/dashboard/` — web UI (optional, opt-in)
- `elephantq/features/` — scheduling, recurring, metrics, logging, webhooks, dead-letter, security (optional, opt-in)

## Getting Started

```bash
git clone https://github.com/yourusername/elephantq.git
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

Set up a test database:

```bash
createdb elephantq_test
export ELEPHANTQ_DATABASE_URL="postgresql://user:password@localhost/elephantq_test"
```

## Running Tests

```bash
python -m pytest tests/ -v
```

## Coding Standards

- Use async/await consistently
- Add type hints for public APIs
- Keep error messages actionable
- Add tests for new behavior
