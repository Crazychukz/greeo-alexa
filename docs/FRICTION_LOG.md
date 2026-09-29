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
- **Actual result:** The SDK returns `str(exc)` as the tool result, for example "Error executing tool tell_tale: 1 validation error for tell_taleArguments … https://errors.pydantic.dev/…". There is no setting to change this, and at the middleware layer the result arrives as a camelCase wire-format dict rather than a `CallToolResult`, which is undocumented. Also, v2 renamed `FastMCP` to `MCPServer`, so most tutorials no longer run.
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
