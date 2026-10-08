# Friction log

Genuine problems with a document, SDK, or tool that cost more than 10 minutes while
building Greeo. Each entry follows the hackathon's friction-log format. Entries are
written when the friction happens, not reconstructed afterwards.

## Entry template

### YYYY-MM-DD: Short title

- **Tool / doc:** name, version, and URL
- **Task attempted:**
- **Steps taken:**
- **Expected result:**
- **Actual result:**
- **Severity:** Critical | High | Medium | Low
- **Workaround used:**
- **Actionable suggestion:**

## Entries

### 2026-10-07: Strands Agents pins the MCP SDK below the current release

- **Tool / doc:** Strands Agents SDK `strands-agents` 1.58.1 (PyPI), with the `mcp` Python SDK
- **Task attempted:** Add a Strands agent as the simulator's host, alongside an MCP server already built on `mcp` 2.2.0.
- **Steps taken:** Downloaded the wheel and read its metadata; found `Requires-Dist: mcp<2.2,>=1.23.0`. Installed `mcp` 2.1.1 with Strands in a scratch environment, checked every MCP import Greeo uses, then ran the full test suite there before changing the real pins.
- **Expected result:** An agent SDK that works with the current MCP SDK, or a documented reason for the cap.
- **Actual result:** Installing Strands would silently downgrade the MCP SDK under a working server. Strands' own compatibility layer supports both the 1.x and 2.x lines, so the reason for the `<2.2` cap is not stated anywhere we could find. Separately, when the model hits its output limit, the agent raises `MaxTokensReachedException` rather than returning what it has, so a host must catch it explicitly.
- **Severity:** Medium
- **Workaround used:** Pinned `mcp==2.1.1` after the full suite passed on it, and treated `MaxTokensReachedException` as "no tool called", so Greeo's own tools answer.
- **Actionable suggestion:** Document why the MCP SDK is capped and track new MCP releases promptly; list `MaxTokensReachedException` on the agent-loop page as something an agent must handle.

### 2026-09-30: Account-linking docs leave the resource-server side unspecified

- **Tool / doc:** Alexa+ MCP Toolkit,
  [Account Linking for MCP Add-ons](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-account-linking.html)
  and [QuickStart](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html)
- **Task attempted:** Design how Greeo's MCP server identifies a listener for per-user memory (saved stories, where they stopped).
- **Steps taken:** Read the account-linking page, the quickstart, the functional requirements and the MCP authorization spec; compared them.
- **Expected result:** A description of what the MCP server receives and must check: the header carrying the token, the token format and claims, how to validate the audience, and how to tell one customer from another.
- **Actual result:** The page covers the authorization-server side well (PKCE, redirect URIs, resource parameter) but says only that "Alexa includes this access token in every request" and that the add-on "uses it to identify the customer". It does not name the header, the token format, or any claim to use as the customer identifier. The quickstart says to return 401 "without a `WWW-Authenticate` header", which differs from the MCP spec's example; neither page explains why. No identifier is documented for unlinked customers, so per-user state is impossible without account linking, and that is not stated either.
- **Severity:** Medium
- **Workaround used:** Followed the MCP authorization spec for the missing parts (`Authorization: Bearer`, audience validation, 401 on invalid tokens), mapped `issuer + subject` to a local user, and kept story tools open to guests.
- **Actionable suggestion:** Add a "What your MCP server receives" section with a sample request, the token's format and claims, a validation checklist, the recommended customer identifier, and a note that unlinked customers have no stable identity.

### 2026-09-28: Conflicting MCP protocol version in the Alexa+ docs

- **Tool / doc:** Alexa+ MCP Toolkit docs,
  [Overview](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-overview.html) and
  [Client and App Lifecycle](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-client-lifecycle.html)
- **Task attempted:** Decide which MCP protocol version Greeo's server must negotiate with Alexa+.
- **Steps taken:** Read the toolkit overview, then the client lifecycle page for the initialize handshake.
- **Expected result:** One version, stated consistently.
- **Actual result:** The overview says Alexa+ supports "the 2025-11-25 version of the MCP specification", but both initialize examples on the lifecycle page show `"protocolVersion": "2025-03-26"`. It is unclear which version the client actually sends.
- **Severity:** Medium
- **Workaround used:** Negotiate both versions and treat a missing `MCP-Protocol-Version` header as 2025-03-26, as the MCP spec advises.
- **Actionable suggestion:** Update the lifecycle examples to the version Alexa+ really sends, and list every supported version on the overview page.

### 2026-09-29: MCP Python SDK sends validation and exception text to the client

- **Tool / doc:** `mcp` Python SDK 2.2.0 (`mcp/server/mcpserver/server.py`, `_handle_call_tool`)
- **Task attempted:** Make sure no tool name, field name or technical message can reach an Alexa+ customer, as the functional requirements demand.
- **Steps taken:** Called a tool with an invalid argument through the SDK client; read the server source; added a middleware and inspected what it receives.
- **Expected result:** A generic or configurable error message for argument-validation failures and unexpected exceptions.
- **Actual result:** The SDK returns `str(exc)` as the tool result, for example "Error executing tool tell_tale: 1 validation error for tell_taleArguments … https://errors.pydantic.dev/…". There is no setting to change this, and the SDK client hides HTTP status codes too: a 401 or 429 from the server surfaces only as `MCPError: Server returned an error response`, so a host cannot tell a rejected token from an outage without a second plain HTTP request. At the middleware layer the result arrives as a camelCase wire-format dict rather than a `CallToolResult`, which is undocumented. Also, v2 renamed `FastMCP` to `MCPServer`, so most tutorials no longer run.
- **Severity:** High for voice products (the text becomes speech); Medium otherwise.
- **Workaround used:** A server middleware that rewrites any error result without Greeo's own error marker into a plain-language message, handling both the dict and model forms; handlers catch everything else themselves.
- **Actionable suggestion:** Add a server option for a customer-safe error formatter, and document the result type middleware receives for `tools/call`.

### 2026-09-28: No documented answer on whether tool text is spoken verbatim

- **Tool / doc:** Alexa+ MCP Design Guide,
  [The Conversation Surface](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-conversation-surface.html);
  [SSML reference](https://developer.amazon.com/en-US/docs/alexa/custom-skills/speech-synthesis-markup-language-ssml-reference.html)
- **Task attempted:** Find out whether a story beat returned by a tool is read to the customer as written, and whether SSML is supported, for a storytelling add-on where wording matters.
- **Steps taken:** Read the conversation surface, tools and data design, display modes, and layout pages, the toolkit overview and the API reference; searched for SSML guidance for MCP add-ons.
- **Expected result:** A clear statement of how tool text becomes speech, and whether a tool can request verbatim delivery or use speech markup.
- **Actual result:** Only "You influence Alexa's response through the data you return, not by scripting it directly." Nothing says whether text is ever read verbatim, how much it may be shortened, or whether SSML is honoured; the SSML reference covers classic custom skills only.
- **Severity:** High for narrative add-ons (stories, recipes read step by step, instructions), where rewording changes the product.
- **Workaround used:** Keep beats short and self-contained, put the exact text on an MCP Apps card, return plain text only, and label verbatim delivery as simulator behaviour in Greeo's demo.
- **Actionable suggestion:** Document how tool output is turned into speech, and offer a supported way to mark text for verbatim delivery (for example a `_meta` hint), with any limits.

### 2026-10-07: Polly neural voices are not offered in eu-north-1

- **Tool / doc:** Amazon Polly `SynthesizeSpeech`, boto3,
  [Voices in Amazon Polly](https://docs.aws.amazon.com/polly/latest/dg/available-voices.html)
- **Task attempted:** Switch Greeo's storyteller voice from browser speech to Polly, in the same region as Bedrock (eu-north-1).
- **Steps taken:** Added the IAM permission, then called `SynthesizeSpeech` with neural voices (Ayanda, Gregory, Arthur, Brian) in eu-north-1; retried the same calls in us-east-1 and eu-west-1.
- **Expected result:** Neural voices available wherever Polly is, or an error that names the region as the problem.
- **Actual result:** Every neural call in eu-north-1 failed with `ValidationException: The selected engine is not supported...`, which reads like a voice or engine mismatch. The same calls succeeded at once in us-east-1. Generative and long-form voices are in fewer regions again, and Gregory has no generative engine at all.
- **Severity:** Medium
- **Workaround used:** A separate `POLLY_REGION` setting (us-east-1), so Bedrock stays in eu-north-1.
- **Actionable suggestion:** Say in the error which engines the current region supports, and add a region-by-engine table to the voices page.

### 2026-10-01: Nova Lite returned the JSON schema instead of an answer

- **Tool / doc:** Amazon Bedrock Converse API, `eu.amazon.nova-lite-v1:0`
- **Task attempted:** Get a structured JSON answer (a retold story) by giving the model a JSON schema in the prompt.
- **Steps taken:** Sent the same prompt and schema that Kimi K2.5 and Qwen3 answered correctly.
- **Expected result:** A JSON object matching the schema.
- **Actual result:** On one headline Nova Lite copied the schema itself back (`properties`, `type`, `required`) instead of filling it in. Nothing in the response marks it as a failure, so it only shows up as a validation error.
- **Severity:** Low (one in about a dozen calls)
- **Workaround used:** Validate every answer and retry once with a repair prompt; Kimi K2.5 and Qwen3 for the editorial prompts.
- **Actionable suggestion:** Document structured output for Nova through Converse (tool use or a JSON mode), with an example that passes a schema.

### 2026-10-01: Bedrock Anthropic models fail with an unexplained Marketplace error

- **Tool / doc:** Amazon Bedrock Converse API, Anthropic models; [Access Amazon Bedrock foundation models](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)
- **Task attempted:** Compare Claude with other Bedrock models as the tale writer.
- **Steps taken:** Called Converse for each candidate model with the same IAM user; Nova, DeepSeek, Qwen3, Kimi K2.5 and gpt-oss all worked.
- **Expected result:** Claude works like the others, or the error names the one permission to add.
- **Actual result:** "Model access is denied due to IAM user or service role is not authorized to perform the required AWS Marketplace actions (aws-marketplace:ViewSubscriptions, aws-marketplace:Subscribe)… Your AWS Marketplace subscription for this model cannot be completed at this time." Model access pages now say models are enabled by default, so it is unclear why Marketplace is involved, or whether one subscription call is enough. Listing inference profiles needed further permissions too.
- **Severity:** Medium
- **Workaround used:** Used Kimi K2.5 and Qwen3, which need no Marketplace subscription.
- **Actionable suggestion:** Explain on the model-access page which providers go through Marketplace, and give the minimal IAM policy for a first call in the error itself.
