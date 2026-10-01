# Identity and Alexa+ account linking

How Greeo knows who is listening: what works today, and the production design for
Alexa+. Each part is labelled **Implemented** or **Designed (not built)**.

Sources, read on 2026-09-30:

- Alexa+ account linking for MCP add-ons: <https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-account-linking.html>
- Alexa+ MCP quickstart: <https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html>
- Alexa+ functional requirements, section 6: <https://developer.amazon.com/docs/alexaplus/add-ons/functional-requirements.html>
- MCP authorization, 2025-11-25: <https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization>

## Summary

| Area | Status |
| --- | --- |
| Identity resolved from the request only, never from a tool argument | **Implemented** |
| Guest access to all story tools | **Implemented** |
| Demo bearer tokens (hash stored, revocable) | **Implemented**, for the simulator only |
| Development header, DEBUG only, startup check | **Implemented** |
| HTTP 401 for an unknown or revoked bearer token | **Implemented** |
| Per-user isolation of all memory | **Implemented**, tested across every tool |
| Per-token rate limit, log redaction | **Implemented** |
| OAuth 2.1 access-token validation (signature, issuer, audience, expiry) | **Designed** |
| Protected Resource Metadata at `/.well-known/oauth-protected-resource` | **Designed** |
| Authorization server (login, consent, tokens, refresh) | **Designed**; Greeo would use an existing one, not build one |
| HTTP 401 on memory tools to start Alexa's linking flow | **Designed** |

**The demo token scheme is not Alexa+ production authentication.** It exists so the
simulator and judges can act as a named listener. Alexa+ would never send a `greeo_…`
token; it sends an OAuth access token obtained through account linking.

## What is implemented

`backend/apps/mcp_server/identity.py` resolves one of three callers:

1. **Demo bearer token**: `Authorization: Bearer greeo_…`. `manage.py create_demo_user <name>` prints a token once; only its SHA-256 hash is stored (`ApiToken`). Tokens can be revoked in the admin or with `--revoke-existing`.
2. **Development header**: `X-Greeo-User`, honoured only when `DEBUG` and `MCP_ALLOW_DEV_IDENTITY` are both on. If the setting is on without `DEBUG`, the server refuses to start and `manage.py check` fails (`greeo.E001`). Production settings force it off.
3. **Guest**: no credentials. Every story tool works; memory tools explain that an account is needed.

`backend/apps/mcp_server/gate.py` sits in front of `/mcp`: a bearer token that is present
but unknown or revoked gets HTTP 401; request rates are limited per token (per client
address for guests). Every memory function takes the user explicitly and filters by it.

## What Alexa+ requires (from the current docs)

Quoted from the account-linking page unless noted.

- **Grant type:** "Alexa+ add-ons support only the Authorization Code Grant. The implicit grant isn't supported."
- **PKCE:** S256 is mandatory. "Deployment is blocked if your authorization server doesn't support S256." The CLI checks `code_challenge_methods_supported` in the authorization server metadata.
- **Protected Resource Metadata** at `https://<server>/.well-known/oauth-protected-resource`, containing `resource`, `authorization_servers` and `scopes_supported`.
  - `resource`: "Must exactly match the URL in your add-on manifest — including or excluding any trailing slash."
  - `authorization_servers`: "Alexa uses only the first entry in this list."
- **Resource parameter:** Alexa sends `resource` (the MCP server's canonical URI) "in both the authorization request and the token exchange request but not in the token refresh request".
- **Client registration:** "Static client registration — Dynamic Client Registration (DCR) isn't supported." A client id (and optional secret) is created on the authorization server and given to Alexa with `alexa-ai configure-account-linking`.
- **Redirect URIs:** "Alexa uses multiple redirect URIs"; "Register all of them"; "Use exactly the value Alexa passes — don't hardcode a single URI."
- **Refresh tokens:** "Your token endpoint must return a refresh token alongside every access token."
- **Unauthenticated calls:** when a tool that needs identity is called before linking, "Your MCP server must return a `401` or `403` response." The quickstart adds that the server "returns `401 Unauthorized` (without a `WWW-Authenticate` header)".
- **Guests:** "Provide a functional guest experience for APIs/tools that don't require linking so unlinked customers aren't dead-ended." (functional requirements)
- **Account switching:** "Your server must not return data from a previously linked account after a customer links a different account — scope all data to the currently authorized token." (functional requirements)

What the Alexa+ docs do not say, recorded so nothing is assumed:

- The header Alexa uses to send the token. The page says only that "Alexa includes this access token in every request". The MCP spec requires `Authorization: Bearer <access-token>` on every request, which this design follows.
- How to map a token to a user. "Your add-on uses it to identify the customer" is the whole of the guidance.
- Any Alexa-supplied user or device identifier for unlinked customers. None is documented, so a guest has no stable identity.

From the MCP authorization spec, which Alexa+ builds on:

- "MCP servers **MUST** validate that access tokens were issued specifically for them as the intended audience."
- "Invalid or expired tokens **MUST** receive a HTTP 401 response." Insufficient scope is 403.
- "Access tokens **MUST NOT** be included in the URI query string."
- "The MCP server **MUST NOT** pass through the token it received from the MCP client."

## Production design (not built)

```mermaid
sequenceDiagram
    participant U as Customer
    participant A as Alexa+
    participant AS as Authorization server
    participant G as Greeo MCP server
    U->>A: "Save this story"
    A->>G: tools/call save_for_later (no token)
    G-->>A: HTTP 401
    A->>G: GET /.well-known/oauth-protected-resource
    G-->>A: resource, authorization_servers[0], scopes_supported
    A->>AS: authorization request (code, PKCE S256, resource, redirect_uri)
    U->>AS: signs in and consents
    AS-->>A: code, then access token + refresh token
    A->>G: tools/call save_for_later, Authorization: Bearer <access token>
    G->>G: verify signature, issuer, expiry, audience = our resource URI
    G->>G: EndUser for (issuer, subject); save for that user only
    G-->>A: result
```

1. **Roles.** Greeo's MCP server is the OAuth resource server. It does not issue tokens or show login pages. An existing authorization server does that; Greeo would use a managed one, not write its own. Before choosing one, confirm from its metadata that it lists `S256` in `code_challenge_methods_supported`, issues refresh tokens, supports static client registration with several redirect URIs, and binds tokens to the `resource` Alexa sends.
2. **Protected Resource Metadata.** Serve `/.well-known/oauth-protected-resource` with `resource` set to the exact deployed MCP URL, one authorization server, and `scopes_supported: ["greeo.memory"]`. The installed MCP SDK (`mcp` 2.2.0) has settings for this (`AuthSettings`, `TokenVerifier` on `MCPServer`); that is the intended route, to be verified against its source when built.
3. **Scopes.** One scope, `greeo.memory`, covering listening progress, saves and preferences. Story tools need no scope.
4. **Token validation on every request.** Verify the signature against the authorization server's published keys, the issuer, the expiry, and that the audience is Greeo's own `resource` URI. Reject anything else with 401. Tokens are never logged (already enforced by the log filter) and never forwarded to another service.
5. **Mapping the subject to a listener.** `EndUser.external_id = "oauth:<issuer>#<subject>"`, created on first use with `get_or_create_user`. The subject is an opaque identifier; Greeo stores no name or email. `identity.current_user` would return this user in place of the demo-token lookup; nothing else in Greeo changes, because every memory function already takes the user explicitly.
6. **Account switching.** A different linked account has a different subject, so it maps to a different `EndUser` and sees none of the previous account's data. This is the same isolation the tests already prove for two users.
7. **When to return 401.** Story tools (`search_events`, `get_briefing`, `tell_tale` and the truth layers) stay open to guests. Memory tools (`save_for_later`, `get_saved_stories`, `set_preferences`) would return HTTP 401 without a valid token so Alexa starts linking. Today they return a plain-language message instead, which suits the simulator. For a guest, `tell_tale` simply records nothing.
8. **Refresh and expiry.** Handled between Alexa and the authorization server. Greeo only has to answer 401 for an expired token.

### Open points to settle when building

- The quickstart says 401 "without a `WWW-Authenticate` header", while the MCP spec lets a server advertise its metadata in that header or at the well-known URI. Serving the well-known document satisfies both; follow the quickstart and omit the header for Alexa.
- Deciding per tool whether to return 401 means reading the JSON-RPC body before the MCP handler runs. The gate would do this for `tools/call` requests.
- Privacy policy and terms of use URLs are required for certification and must describe what `greeo.memory` stores and how to delete it (`reset_context(forget_history=True)` exists for deletion).
