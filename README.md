# Greeo

Greeo is a voice-first news storytelling experience for the Amazon Alexa+ hackathon. It turns evidence-backed events into short tale beats, then lets people explore the truth behind them through facts, context, perspectives, and sources.

## Phase 1: run the stack

```sh
make up
make migrate
curl http://localhost:8000/healthz
make test
make lint
```

The six local services are Django web, a placeholder MCP process, Celery worker, Celery beat, PostgreSQL, and Redis. The MCP process is intentionally a placeholder until Phase 8.

