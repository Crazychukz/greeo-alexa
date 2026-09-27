# Evidence-depth options for Greeo

**Status:** research only — no adapter or pipeline code has been added.

**Research date:** 2026-09-26. This is an engineering and product assessment,
not legal advice. Re-check provider terms immediately before production use.

## Decision context

Prompt 5 intentionally stores only RSS metadata: a headline, cleaned URL, source,
date, and up to 300 characters of plain-text snippet. That is appropriate for
compliant discovery, but usually not enough to establish CONTEXT or materially
different PERSPECTIVES. Any richer evidence must preserve Greeo's rules: no article
page scraping, evidence links on every claim, no copied bodies, and no LLM invention.

## Multi-outlet coverage is a separate requirement

Greeo should not depend on one publisher. The current RSS architecture already models
each outlet as a separate `SourceFeed`, so it can support a broad, deliberately chosen
set of direct publisher feeds. Before enabling a feed, its terms must be reviewed and
recorded, and the existing policy gate must continue to retain only the headline,
cleaned URL, source name, date, and at most 300 characters of snippet. This gives
source diversity without mistaking an aggregator licence for a licence to repurpose
publisher prose.

For automatic event discovery across **many** outlets, a second provider can help find
and cluster coverage. It is not, by itself, clearance to pass article bodies into an
LLM. The comparison below separates these two jobs.

| Route | Coverage and role | What Greeo may safely plan to retain now | Editorial-text decision |
| --- | --- | --- | --- |
| Reviewed direct publisher RSS feeds | Many owner-approved outlets, each with its own terms | Existing bounded RSS metadata only | No bodies; add feeds only after their individual terms review. |
| [GDELT DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) | Global discovery; searches coverage in 65 machine-translated languages and can return article titles/URLs | Discovery metadata and links, with GDELT citation | Do not treat linked publisher articles as licensed source text. Its Context API returns matched sentences, which should not be used to bypass Greeo's 300-character/source-text policy. |
| [NewsAPI.org](https://newsapi.org/pricing) | Multi-outlet headline/discovery API | Its bounded metadata, subject to terms | It does not provide full article content; the free Developer plan is development/testing only, with 100 requests/day and 24-hour-delayed articles. |
| [TheNewsAPI](https://www.thenewsapi.com/documentation) | Thousands of outlets and over one million articles added weekly | Titles, descriptions, short snippets, links, and source metadata | Its FAQ says it supplies only short snippets and links, not full article content. It is a possible metadata-only adapter, not a depth solution. |
| [NewsAPI.ai / Event Registry](https://www.eventregistry.org/) | Claims over 150,000 sources in 60+ languages, clustering and enriched metadata | Evaluate only; do not ingest bodies into editorial context under the public terms | It can return full text, but its terms say publisher rights are the customer's responsibility and that it does not grant or broker those rights. |

### Implication for a broad source set

The practical architecture is **many reviewed direct feeds for public provenance**,
optionally supplemented by an aggregator for event discovery/deduplication, plus a
separate licensed or owner-curated rich-evidence path. This prevents a single provider
from becoming Greeo's only viewpoint while preserving a clear permission boundary.

## Option A — multi-outlet aggregator research

### A1. GDELT: broad discovery and clustering, not fuller evidence

GDELT's DOC API is useful for surfacing global coverage and the ArticleList output
returns titles and URLs. GDELT describes its search as covering 65
machine-translated languages. Its Context API can return a matched sentence and nearby
text, but that does not turn the linked publisher article into reusable prose.
[DOC API overview](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/), [Context
API overview](https://blog.gdeltproject.org/announcing-the-gdelt-context-2-0-api/)

For Greeo, use GDELT only to discover candidates and measure that an event is covered
by multiple outlets. Keep Greeo's own per-source RSS policy as the content boundary;
do not use GDELT snippets as a way to assemble an LLM prompt from publisher text.

| Assessment | Result |
| --- | --- |
| Layers improved | Discovery, clustering, source diversity, and SOURCES; not licensed depth for FACTS, CONTEXT, or PERSPECTIVES. |
| Engineering effort | 6–8 hours for a metadata-only adapter, attribution, Redis cache, rate limit, policy gate, and fixtures. |
| Cost | [GDELT's terms](https://gdeltproject.org/about.html) describe its released datasets as free/unrestricted with a required GDELT citation and link; confirm the specific endpoint's current service limits before launch. |
| Main risks | Search/ranking bias, duplicated syndication, changing public-service limits, and confusing a link index with rights to article prose. |
| Decision | **Good optional discovery layer; not a rich-evidence adapter.** |

### A2. NewsAPI.org and TheNewsAPI: broad metadata, still no depth

NewsAPI.org's free Developer plan is restricted to development/testing, has a 100
request/day limit, and delays articles by 24 hours; its paid Business plan is currently
listed at US$449/month. It explicitly says users remain responsible for third-party
content rights and must retain attribution. [Pricing](https://newsapi.org/pricing),
[terms](https://newsapi.org/terms)

TheNewsAPI says it covers thousands of sources, and returns title, description, a
60-character snippet, URL, date, and source fields. Its FAQ expressly says it does
not provide full article content. [Documentation](https://www.thenewsapi.com/documentation),
[FAQ](https://www.thenewsapi.com/faq), [terms](https://www.thenewsapi.com/tos)

| Assessment | Result |
| --- | --- |
| Layers improved | Discovery and SOURCES; only limited FACTS from bounded snippets. |
| Engineering effort | 4–6 hours per metadata-only adapter, including attribution, cache/rate controls, gate, and fixtures. |
| Cost | NewsAPI.org: free developer use only, then US$449/month listed for Business. TheNewsAPI has a free tier, but its current request allowance/paid prices must be confirmed at selection time. |
| Main risks | Neither solves the fuller-evidence requirement; provider terms and publisher rights still govern reuse. |
| Decision | **Possible secondary discovery adapters, not the answer to contextual editorial depth.** |

### A3. NewsAPI.ai / Event Registry: large-scale evaluation candidate, no public-text clearance

NewsAPI.ai markets access to more than 150,000 outlets in 50+ languages, full article
content, event clustering, and 2,000 free searches. Its listed 5K plan is currently
US$90/month. [Plans](https://newsapi.ai/plans) Event Registry describes comparable
global coverage and its public terms state that free access is testing-only; more
importantly, it says that rights in third-party publisher content remain the customer's
responsibility and it does not grant or broker publishing rights. [Event Registry
terms](https://beta.eventregistry.org/terms)

| Assessment | Result |
| --- | --- |
| Layers improved | Technically all discovery and evidence-preparation layers, including clustering and metadata enrichment. |
| Engineering effort | 10–14 hours for a constrained proof-of-concept adapter, source attribution, cache/rate controls, policy gate, and fixtures; further time for written rights clearance. |
| Cost | 2,000 free evaluation searches; current public 5K plan US$90/month. Free Event Registry access is testing only. |
| Main risks | Full-text availability is **not** a publisher-content licence. Public terms put copyright compliance on Greeo, so do not send returned article bodies to the LLM or publish derivations without a separate written content licence. |
| Decision | **Evaluate only if the provider and/or participating publishers give written rights covering storage and LLM-derived output.** |

## Option B — Guardian Open Platform Content API: investigate, do not use for Greeo

The Guardian's **Developer** key is explicitly intended for non-commercial projects
including hackathons. It is free, offers article text, and currently allows one request
per second and 500 requests per day. It therefore appears attractive on access and
cost alone. [Access terms](https://open-platform.theguardian.com/access/)

It is **not compatible with Greeo's editorial workflow**. The current Open Platform
terms prohibit use of its content for machine-learning/AI purposes and prohibit using
AI technologies to generate, synthesise, or combine content. The same terms require an
API key, delete-or-refresh of held content within 24 hours, retention of headline,
byline and copyright notices, a link to the original article, and a Powered by The
Guardian logo for republished or tool-based content. [Open Platform terms](https://www.theguardian.com/open-platform/terms-and-conditions)

| Assessment | Result |
| --- | --- |
| Layers improved | In theory: FACTS, CONTEXT, PERSPECTIVES, and SOURCES. In practice: not for the LLM/editorial use Greeo needs. |
| Engineering effort | 6–10 hours for an adapter, attribution, 24-hour expiry, caching, and tests — **do not spend this time without written rights**. |
| Cost | Free only for eligible non-commercial use; commercial access is custom-priced. |
| Main risks | Direct terms conflict with the planned LLM-derived telling and evidence workflow; 24-hour retention conflicts with durable evidence/audit needs; mandatory presentation/attribution requirements. |
| Decision | **Reject for the current hackathon build.** Do not ingest Guardian full text or summaries into Greeo's LLM context. |

## Option C — Wikimedia reference material

### B1. Wikipedia prose via API

Wikipedia can add useful background context: definitions, historical timelines, and
links to further sources. It is not an appropriate primary source for a current event
or a substitute for independently sourced perspectives.

Most Wikimedia text is available under **CC BY-SA 4.0** (and GFDL). Reuse requires a
link/URL to the reused page or an equivalent credited copy, an indication of changes,
and, when reused text is modified or added to, distribution under CC BY-SA 4.0 or later.
The governing Terms of Use also warn that individual pages can carry additional source
attribution requirements. [Wikimedia Terms of Use](https://foundation.wikimedia.org/wiki/Terms_of_Use)

For an LLM-generated telling or context statement that closely transforms Wikipedia
prose, the derivative-work question is fact-specific. Treat it as potentially adapted
material unless a qualified adviser says otherwise. That means Greeo would need a
visible attribution and licence path for any published adapted text. Merely linking to
a page is not a blanket solution for every generated output. This option is therefore
**not recommended for the initial demo**.

API use itself requires a meaningful User-Agent, serial or low-concurrency requests,
caching, and honouring 429/Retry-After. Current Wikimedia documentation lists 200
requests/minute for identified unauthenticated clients, but Greeo should use a much
lower application limit. [API access policy](https://www.mediawiki.org/wiki/Wikimedia_APIs/Access_policy), [rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits), [API etiquette](https://www.mediawiki.org/wiki/API:Etiquette)

| Assessment | Result |
| --- | --- |
| Layers improved | Primarily CONTEXT and SOURCES; weak for current-event FACTS and PERSPECTIVES. |
| Engineering effort | 8–12 hours for title resolution, revision IDs, Redis caching, rate limits, visible attribution, licence metadata, and tests. |
| Cost | No API fee at small compliant volumes. |
| Main risks | ShareAlike/attribution obligations, factual accuracy and recency, editorial bias, and ambiguity over whether generated text is an adaptation. |
| Decision | **Do not select without an explicit CC BY-SA publication/attribution plan.** |

### B2. Wikidata structured statements: safer optional complement

Wikidata is not prose context, but its main structured-data namespaces are **CC0**.
It can provide identifiers, dates, locations, and links that help disambiguate a
curated event. Attribution is not required, though Wikidata asks reusers to credit it.
[Wikidata reuse guidance](https://www.wikidata.org/wiki/Wikidata:Reuse)

This avoids Wikipedia prose's ShareAlike issue, but it cannot provide nuanced
explanations or contested perspectives. It is suitable only as a bounded reference
support layer with source URLs and confidence checks.

| Assessment | Result |
| --- | --- |
| Layers improved | SOURCES and limited factual/contextual disambiguation. |
| Engineering effort | 4–6 hours for a small structured lookup adapter, cache, rate limiter, and fixtures. |
| Cost | No API fee at compliant low volume. |
| Main risks | Sparse or stale records; statement references vary; cannot replace news evidence. |
| Decision | Viable **fallback complement**, not the primary rich-evidence solution. |

## Option D — owner-curated richer evidence

For a selected event, the project owner supplies their own words for richer evidence:
an expanded factual note, background/context items, clearly attributed reported
positions, exact source URLs, publication dates, and the reason each item matters.
The owner must not paste article bodies or long quotations. Every item remains linked
to its source, and contentious claims remain labelled as reported claims or viewpoints.

This is the clearest fit for the golden demo event and Greeo's evidence policy. It gives
the LLM only supplied/stored, attributable material; no provider's article text is
silently transformed. It also works with the planned deterministic validators and later
pipeline gates.

| Assessment | Result |
| --- | --- |
| Layers improved | FACTS, CONTEXT, PERSPECTIVES, SOURCES, and responsible moral/reflection review. |
| Engineering effort | 3–5 hours for a YAML schema/loader once Prompt 2B's shared validators are available, plus owner editorial time per event. |
| Cost | No API fee; owner editorial time. |
| Main risks | Small coverage and manual workload; quality depends on source review and careful neutral wording. |
| Decision | **Recommended for the hackathon's first publishable event.** |

## Option E — combinations

| Combination | Layers improved | Effort | Risks and limits |
| --- | --- | --- |
| Many reviewed direct RSS feeds + owner-curated rich event pack | All demo layers plus a broad set of public source links | 3–5 engineering hours for the loader plus curation and per-source terms review | Best traceability; richest content remains curated until a separately licensed pipeline is chosen. |
| Many reviewed feeds + GDELT discovery + owner-curated rich event pack | Adds cross-outlet discovery and event-candidate clustering | 9–13 hours total plus curation | GDELT is discovery only; avoid source-text aggregation. |
| Owner-curated pack + Wikidata CC0 lookup | Adds entity/date/location disambiguation and extra source links | 8–11 hours total | Structured data may be incomplete; do not promote it to a news source or perspective. |
| Owner-curated pack + Wikipedia prose | Adds broader background prose | 11–17 hours total | Requires an explicit CC BY-SA attribution and publication decision; not recommended for this deadline. |
| NewsAPI.ai/Event Registry full text + anything | Potentially rich technical input from 150,000+ outlets | 10–14 hours plus rights work | Reject until a written licence specifically covers storage, LLM processing, derived tellings, and required attribution/deletion rules. |
| Guardian full text + anything | Potentially rich, but unusable for Greeo's LLM workflow | Not recommended | Current Guardian terms prohibit the AI use Greeo requires. |

## Recommendation and fallback

**Recommended hackathon plan:** expand Prompt 5 from the initial example feed to a
deliberately diverse, owner-reviewed set of direct publisher RSS feeds. Use those feeds
for breadth and source links, and choose **owner-curated richer evidence** for the
golden event. Store the owner-written evidence and its attribution in a future,
schema-validated event pack; use it as the sole richer context supplied to the
editorial workflow. This is the lowest-risk way to demonstrate both broad news
coverage and a trustworthy, evidence-backed experience.

**Fallback:** add a metadata-only **GDELT discovery adapter** after the curated loader,
then a narrowly scoped **Wikidata CC0** reference adapter. They improve breadth,
disambiguation, and source links, but must not create unsourced narrative context or
perspectives.

## Decision required before implementation

Choose one of the following. I will then implement **only** that adapter/loader under
`backend/apps/news/adapters/`, with attribution fields, Redis caching, rate limits, the
same policy gate, and synthetic-fixture tests.

1. **Many reviewed RSS feeds + curated rich evidence** — recommended: breadth from many outlets, depth from owner-supplied evidence.
2. **Many reviewed RSS feeds + GDELT discovery + curated rich evidence** — recommended if cross-outlet event discovery is valuable now; GDELT remains metadata-only.
3. **Add Wikidata CC0** — optional structured reference support, after option 1 or 2.
4. **Wikipedia prose** — only after you accept the CC BY-SA attribution and ShareAlike implications for published adapted output.
5. **NewsAPI.ai / Event Registry evaluation** — only after written rights cover storage, LLM processing, derived output, attribution, caching, and deletion; public terms alone are insufficient.
