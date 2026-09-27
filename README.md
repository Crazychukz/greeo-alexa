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

## Project history

Greeo's concept began as a web prototype for the [Gemini 3 Hackathon](https://devpost.com/software/greeo): paste a news link, get it retold as a story with proverbs. This repository is a clean rebuild for Alexa+, started during the Amazon Developer Hackathon submission period. No prototype code is reused.

What is new in this build:

- A self-hosted MCP server and an Alexa+ simulator, designed for voice first: tales told in short beats, with the facts, context, perspectives, and sources one question away.
- Stories are prepared ahead of time from terms-reviewed news feeds, so no model runs while someone is listening.
- Proverbs are never written by a model. Code inserts only proverbs verified against two citations.
- Every telling is checked against its cited facts and revised at most once before publication.
- Per-user memory: what you heard, saved, and where you stopped.
- Amazon Bedrock replaces Gemini as the optional model provider.

## License

[MIT](LICENSE)

