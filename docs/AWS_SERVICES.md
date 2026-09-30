# AWS services

| Service | Purpose | Code location |
| --- | --- | --- |
| Amazon Bedrock Runtime | Optional production LLM provider through the Converse API. Mock remains the local default. | `backend/apps/llm/backends.py` (`BedrockLLM`) |
| Amazon Polly | Optional speech for the simulator host, one sentence per request, paced per storyteller voice with SSML rate and pauses. Off by default (`SPEECH_BACKEND=mock` falls back to browser speech). Real Alexa+ devices do their own speech. | `backend/apps/simulator/speech.py` (`PollySpeech`) |
| Amazon RDS for PostgreSQL (deployment option) | Durable storage for stories, evidence metadata, and LLM call audit records. Local development uses the Compose PostgreSQL service. | `backend/config/settings/base.py`, `backend/apps/llm/models.py` |
| Amazon ElastiCache for Redis (deployment option) | Redis-backed per-run call and daily token limits. Local development uses the Compose Redis service. | `backend/apps/llm/budget.py` |

Bedrock access is deliberately opt-in. Set `LLM_BACKEND=bedrock`, choose an enabled
`BEDROCK_MODEL_ID`, and configure AWS credentials for the selected `AWS_REGION`.
Prompt-specific overrides use `LLM_<PROMPT_NAME_UPPER>_MODEL_ID`; for example,
`LLM_WRITE_TELLING_MODEL_ID`.
