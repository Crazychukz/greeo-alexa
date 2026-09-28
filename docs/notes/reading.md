# Research notes: MCP, MCP Apps and Alexa+

Read on 2026-09-28. Quotes are verbatim from the pages linked. Each section ends with
what it means for Greeo. Where a document says nothing on a topic, that is recorded too.

## 1. MCP specification 2025-11-25: transports

Source: <https://modelcontextprotocol.io/specification/2025-11-25/basic/transports>

Streamable HTTP rules that Greeo's server must meet:

- One endpoint: "The server **MUST** provide a single HTTP endpoint path … that supports both POST and GET methods."
- Origin: "Servers **MUST** validate the `Origin` header on all incoming connections to prevent DNS rebinding attacks." "If the `Origin` header is present and invalid, servers **MUST** respond with HTTP 403 Forbidden."
- Local binding: "When running locally, servers **SHOULD** bind only to localhost (127.0.0.1)."
- Client Accept: "The client **MUST** include an `Accept` header, listing both `application/json` and `text/event-stream`."
- Notifications and responses from the client: "the server **MUST** return HTTP status code 202 Accepted with no body."
- Requests: the server "**MUST** either return `Content-Type: text/event-stream` … or `Content-Type: application/json`, to return one JSON object."
- GET: the server "**MUST** either return `Content-Type: text/event-stream` in response to this HTTP GET, or else return HTTP 405 Method Not Allowed."
- Sessions are optional: "A server … **MAY** assign a session ID at initialization time" (`MCP-Session-Id`). A stateless server simply never assigns one.
- Version header: clients "**MUST** include the `MCP-Protocol-Version: <protocol-version>` HTTP header on all subsequent requests." With no header, "the server **SHOULD** assume protocol version `2025-03-26`." An invalid or unsupported version "**MUST** respond with `400 Bad Request`."

Changes since 2025-06-18 that matter here
(<https://modelcontextprotocol.io/specification/2025-11-25/changelog>):

- The 403 for invalid Origin was made explicit (PR #1439).
- "Clarify that input validation errors should be returned as Tool Execution Errors rather than Protocol Errors to enable model self-correction" (SEP-1303), meaning `isError: true` results, not JSON-RPC errors.
- Icons on tools and resources (SEP-973), tool-name guidance (SEP-986), JSON Schema 2020-12 as the default dialect (SEP-1613), and experimental tasks (SEP-1686).

**For Greeo:** stateless mode with JSON responses (no SSE needed for our read-only tools); 403 on bad Origin; 405 on GET if we do not stream; accept a missing version header as 2025-03-26 and reject unknown versions with 400; bad tool arguments come back as `isError: true` results with a friendly message.

## 2. MCP Apps extension

Sources: specification <https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx>,
SEP-1865 <https://modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp>,
announcement <https://blog.modelcontextprotocol.io/posts/2025-11-21-mcp-apps/>,
Python SDK <https://py.sdk.modelcontextprotocol.io/api/mcp/server/apps/>.

- Extension id `io.modelcontextprotocol/ui`, negotiated through the `extensions` capability; clients list `"mimeTypes": ["text/html;profile=mcp-app"]`.
- A UI is a `ui://` resource with MIME type `text/html;profile=mcp-app`. A tool links to it with `_meta.ui.resourceUri`; `_meta.ui.visibility` defaults to `["model", "app"]`.
- The host sends the view `ui/notifications/tool-input` and `ui/notifications/tool-result` (with `content`, `structuredContent`, `_meta`).
- The view can send `tools/call`, `ui/message`, `ui/open-link`, `ui/update-model-context` and `ui/request-display-mode` (`inline`, `fullscreen`, `pip`).
- Host context includes `theme`, `displayMode`, `containerDimensions`, `locale` and `styles.variables`.
- Default CSP when `ui.csp` is omitted is restrictive (`default-src 'none'`, inline scripts and styles allowed); extra origins go in `connectDomains` and `resourceDomains`.
- Views run in sandboxed iframes and talk only over `postMessage` JSON-RPC.
- Graceful degradation: tools with a UI must still return meaningful `content` text for hosts without UI support.
- Python SDK: `mcp.server.apps` provides `Apps`, `add_html_resource("ui://…", html)`, an `@apps.tool(resource_uri=…)` decorator and `client_supports_apps(ctx)`. The page does not say which SDK version introduced it; Prompt 8 must check the installed source. Latest `mcp` on PyPI today: 2.2.0.

**For Greeo:** each card is a single self-contained HTML file (no external fonts or CDNs, so no CSP domains needed); every tool keeps full text `content` for voice-only hosts; the simulator host (Prompt 12) must implement the same notifications so cards behave the same there and on Alexa+.

## 3. Alexa+ MCP toolkit and functional requirements

Sources: overview <https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-overview.html>,
quickstart <https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html>,
client lifecycle <https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-client-lifecycle.html>,
functional requirements <https://developer.amazon.com/docs/alexaplus/add-ons/functional-requirements.html>,
local inspector <https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-local-inspector.html>.

Platform facts:

- Overview: Alexa+ supports "the 2025-11-25 version of the MCP specification", Streamable HTTP, tools, resources, prompts, and the MCP Apps extension for "interactive UIs for MCP tools directly in the conversation view".
- Client lifecycle: the initialize examples show `"protocolVersion": "2025-03-26"`, which contradicts the overview (logged in `docs/FRICTION_LOG.md`). The server must negotiate both.
- "The session is based on the customer's previous conversations with Alexa+ rather than an explicit identifier for a session with your MCP App." Alexa+ sends no session id to rely on.
- Quickstart: "Your MCP server must meet a round-trip query response latency of less than 500 ms." It must be reachable at a remote URL; a tunnel such as cloudflared is suggested for local development. Registration is through the `alexa-ai` CLI.
- Local Inspector (`@alexa-ai/addon-local-inspector`, Node.js 24+, ports 6274 and 6277) renders MCP Apps widgets in Alexa device frames but "does **not** simulate Alexa+ voice interactions".

Functional requirements relevant to Greeo (verbatim):

- Context: "Design tool parameters so each can be updated independently"; "Preserve context or provide a clear expiry message after session"; "Clear all accumulated context when the customer explicitly requests a fresh start".
- Errors: "Surface no API codes, tool names, JSON, or internal IDs in any customer-facing response"; "Provide actionable next step for every error"; "Preserve flow state after mid-flow errors".
- Onboarding: "Return a useful, contextually relevant summary when the customer asks 'What can you do?'"
- Search: "Provide a helpful message with alternative suggestions when no results are found"; "Preserve context during search refinement and pagination"; results within 3 seconds.
- Voice-only: "Present a maximum of 5 options with key differentiators and offer pagination"; "Never reference visual elements ('the card shown', 'tap the button') on devices without a screen"; keep voice responses under 30 seconds.
- Cross-modal: "Ensure TTS and on-screen content contain no data contradictions"; "Make all critical displayed information also retrievable by voice."
- Visual: "Auto-scroll long content in sync with TTS"; "Show partner name and branding clearly"; "Display suggestion chips in natural language".
- Tools: "Every tool returned by your server's `tools/list` endpoint must be invocable"; "Provide a valid JSON Schema `inputSchema` for every tool"; "Use the MCP error contract (`isError: true` or JSON-RPC errors) for failures"; "Design your tools so the output of one can feed the next — return stable identifiers"; "Include common synonyms, abbreviations, and alternate spellings in tool parameter descriptions"; "do not over-claim functionality".
- Metadata: "Make no misleading or exaggerated claims about capabilities"; "Provide at least 3 distinct, relevant example phrases"; a privacy policy and terms of use URL are required for certification.

**For Greeo:** the rules already in AGENTS.md (75 words, at most 5 options, no jargon, independent parameters, reset) match these. New: the 500 ms latency target applies per call, a "what can you do" answer is needed, empty search results must suggest alternatives, and the voice and card for the same beat must never disagree.

## 4. Alexa+ design guide: conversation, data, display

Sources: conversation surface <https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-conversation-surface.html>,
tools, schema and data design <https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-tools-schema-data-design.html>,
display modes <https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-display-modes.html>,
layout and rendering <https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-layout-and-rendering.html>,
test your customer experience <https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-test-addon-cx.html>.

- How tool text is spoken: "Alexa incorporates your returned data into the voice response. The customer's utterance and the quality, depth, and breadth of your data shape this spoken reply. You influence Alexa's response through the data you return, not by scripting it directly."
- Tools: "Design each tool to represent one meaningful customer intent." "Declare only what you honor." A tool description should state "when to call it, why it's used, and what it returns."
- Empty results: "Always return an error response" rather than empty data.
- Payload hygiene: "Ship only your own content: no third-party tracking parameters, or upstream deep links." It applies to `structuredContent`, tool descriptions and UI payloads.
- Display modes: inline (default; "Confirmations, summaries, and single-decision flows"), fullscreen (information-dense or multi-step), hydrated (no UI payload; Alexa renders the data natively) and voice-only (the baseline). If a device does not support a mode, "Alexa falls back to text rendering."
- Layout: "You don't need to design for specific device dimensions. Alexa handles sizing for you." The host context on Alexa+ adds `deviceClass`, `maxWidth`, `maxHeight`, `isMobile`, `platform`, `safeAreaInsets` and `deviceCapabilities`. Package widgets as "a single HTML file with all dependencies inlined", version URIs with content hashes (for example `ui://…/widget-a3f9c12b.html`), and keep CSP lists minimal: "Alexa blocks anything not declared."
- Testing: light and dark modes, Echo Show 8 and 15, mobile and voice-only; watch for "voice and screen agreement".

**For Greeo, the biggest finding:** Alexa+ does not promise to speak tool text verbatim. A tale beat returned by `tell_tale` will be phrased by Alexa's model, which may shorten or reword it, and could drop the proverb. Consequences:

1. Tool descriptions and the `spoken` field can ask for faithful delivery, but must not claim it is guaranteed (the requirements forbid over-claiming).
2. The beat text, including the verified proverb and its culture, goes on the MCP Apps card, where it is shown exactly as written. On screen devices the card is the faithful record.
3. Our simulator (Prompt 12) speaks beats verbatim. The demo and submission must say that this is the simulator's behaviour, and that on Alexa+ the model phrases the response from our data.
4. Each beat should be short, self-contained data (one beat per call, which the plan already does), which gives the model little reason to summarise.

## 5. Account linking and identity

Sources: <https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-account-linking.html>, quickstart (above), functional requirements section 6.

- OAuth 2.1 authorization code flow with PKCE S256 is mandatory when linking is used; deployment fails without S256 support.
- "Your server hosts a Protected Resource Metadata (PRM) document at the well-known URI according to RFC 9728" (`/.well-known/oauth-protected-resource`).
- The quickstart says the server "returns `401 Unauthorized` (without a `WWW-Authenticate` header) for unauthenticated requests." The account-linking page says a tool requiring authentication "must return a `401` or `403` response", after which Alexa starts linking.
- Refresh tokens are required in practice: "without refresh tokens, customers must re-link their account every time the access token expires."
- Linking is optional: "If your add-on's tools work the same way for all users … you don't need it."
- "Provide a functional guest experience for APIs/tools that don't require linking so unlinked customers aren't dead-ended."
- "Your server must not return data from a previously linked account after a customer links a different account — scope all data to the currently authorized token."
- No Alexa-supplied user, device or locale identifier for MCP add-ons is documented. The API reference covers add-on lifecycle only.

**For Greeo:** per-user memory (progress, saves, preferences) needs a stable identity, and the only documented source is the OAuth access token from account linking. So: story tools work for everyone (a guest experience); memory tools need linking and return 401 when unlinked; identity comes from the token, never from a tool argument (AGENTS.md rule 8). For the hackathon, the simulator uses a development identity header (DEBUG only), and Prompt 11 documents the production OAuth design.

## 6. Speech markup

Searched for SSML or speech markup support in Alexa+ MCP add-ons.

- Found: the SSML reference and APL speech pages are for classic Alexa Skills Kit custom skills
  (<https://developer.amazon.com/en-US/docs/alexa/custom-skills/speech-synthesis-markup-language-ssml-reference.html>).
- Not found: any Alexa+ MCP add-on page that says SSML in tool results is honoured, or that describes speech markup for add-ons.

**For Greeo:** return plain text only, never SSML. Rhythm and pauses come from punctuation and short sentences in the beats.

## 7. Decisions these notes change or confirm

| Topic | Decision | Source |
| --- | --- | --- |
| Transport | Stateless Streamable HTTP, JSON responses, 405 on GET, 403 on bad Origin | Section 1 |
| Protocol versions | Negotiate 2025-11-25 and 2025-03-26 | Sections 1 and 3 |
| Tool errors | `isError: true` with a friendly next step; no IDs or tool names in text | Sections 1 and 3 |
| Verbatim delivery | Not guaranteed on Alexa+; the card carries exact text; the simulator speaks verbatim and says so | Section 4 |
| Source URLs | Off by default (`INCLUDE_SOURCE_URLS=false`), confirmed by the "no upstream deep links" rule | Section 4 |
| Cards | Single inlined HTML per card, content-hashed `ui://` URIs, no CSP domains, text fallback always present | Sections 2 and 4 |
| Identity | Account linking token in production; development header only in DEBUG; guest access to story tools | Section 5 |
| Speech | Plain text, no SSML | Section 6 |
| Latency | Target under 500 ms per call, which Prompt 9 already tests | Section 3 |
