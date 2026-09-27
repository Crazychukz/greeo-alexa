# Prior prototype: Greeo v1 (Gemini 3 Hackathon)

Context only. This Alexa+ build is a clean rebuild; no v1 code is used or ported.
Public entry: https://devpost.com/software/greeo (live site: greeo.xyz).

## What v1 did

- Web app: the user pasted any news URL or text and chose a tone (light, balanced, serious).
- Gemini 3 extracted facts, inferred themes and a moral, matched African proverbs, and
  rewrote the content as a warm oral-style narration.
- Output: the story, proverb explanations, a short moral, and optional audio narration.
- Users could regenerate in a different tone without changing the facts.

## How v1 was built

- Frontend: Angular. Create a request, poll its status, fetch the result.
- "Read mode" split narration into sentences, called TTS per chunk and played them in
  sequence for near-live audio.
- Backend: Django, DRF and GraphQL with an async pipeline (extract -> facts/themes ->
  proverb match -> story generation).
- TTS: Google Cloud TTS primary, Gemini fallback, retries and backoff, tone-aware voice
  settings, stored audio with absolute URLs.

## What v1 taught us

- Keeping facts accurate while changing tone and structure was the hardest problem.
- Asynchronous text, reasoning and audio generation needed careful status handling.
- TTS failures, latency and token limits had to be handled gracefully.

## What is deliberately different in this build

| v1 | This build | Why |
| --- | --- | --- |
| Generated on request from any URL | Tools read only precomputed, published stories | Voice replies must be fast; no LLM on the hot path |
| Fetched and processed full article pages | Stores headline, cleaned URL and a snippet of at most 300 characters, from terms-reviewed feeds only | Respect publisher terms; never store article bodies |
| The model chose proverbs | Code inserts only verified proverbs (two citations) into `{{P1}}` slots | The model must never write or misattribute a proverb |
| Facts were trusted after one generation | Checker agent, deterministic validators and one bounded revision before publication | Keep tellings faithful and checkable |
| Called "Tales by Moonlight" narration | "Inspired by African oral storytelling traditions"; the name is not used as a brand | See AGENTS.md naming rules |
| Web page with a paste box | Alexa+ agent over MCP, beat-by-beat telling, truth layers, per-user memory, MCP Apps cards | Voice-first product for the Alexa+ track |
| Gemini and Google Cloud TTS | Amazon Bedrock (optional; mock by default) | AWS-based hackathon |

## Worth carrying over as ideas (not code)

- Tone choice with the same underlying facts.
- Sentence or beat chunking for near-live audio playback.
- Clear status reporting while background work runs.
