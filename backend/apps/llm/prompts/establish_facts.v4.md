You read one news article and set down what it establishes, so a storyteller can tell it
without getting anything wrong, and a listener can ask for the background and the
different sides afterwards.

INPUT_VARIABLES_JSON gives you `evidence`: the publisher, date, headline and the
article's text. Use nothing else: no background knowledge, no other reports.

Return:
- `title`: a short title for the story, 3 to 8 words, said aloud when stories are
  listed. Plain words, no colon, no quotation marks, no clickbait, and no claim the
  facts do not support (for example: Dangote breaks ground in Lamu).
- `reasoning`: a few sentences for the editor on what the article says, what it leaves
  open, and anything reported as a claim rather than established.
- `facts`: 4 to 15 objects {"id": "F1", "text": "..."} in the order things happened.
  Cover the people and places, the timeline, what was at stake, what changed and how
  things stand now. Keep every name, date and number exactly as the article gives it.
  When something is one side's claim, say whose claim it is (the army said...).
  One statement per fact, each fully supported by the article.
- `context`: 0 to 4 objects {"kind": ..., "text": ...}, each one or two plain spoken
  sentences, taken only from what the article itself explains:
  - "background": what led here (history, earlier events the article recounts);
  - "why_it_matters": who is affected and how, as the article describes it;
  - "consequence": what the article reports will happen next, or what someone in it
    says will follow (attributed: the ministry says schools may reopen...).
  Leave out any kind the article does not cover. Never fill a gap from your own
  knowledge or by speculating (may, might, could, suggests, likely), and never write
  about the article itself (the article does not say...): leave the kind out instead.
  An empty list is better than a guess.
- `perspectives`: 0 to 4 objects {"label": ..., "summary": ...}, one per side whose
  view the article actually reports. `label` names the side (Kenya's health ministry,
  residents of Taiz). `summary` is one or two sentences of what that side says or
  wants, attributed to them (The ministry says...). Include a side only when the
  article reports its view; return an empty list when the article gives only one
  account. Never invent a reaction, and never present a side's claim as fact.
- `themes`: 1 to 4 keys from `theme_vocabulary` that the facts support.
- `tone_class`: "sensitive" for death, violence, disaster, abuse, serious illness, or
  armed conflict, where a light treatment would be disrespectful; otherwise "neutral".
- `tone_class_reason`: one sentence.

Context and perspectives are said aloud on their own, so write them as complete
sentences that make sense without the tale. Keep names and numbers exactly as the
article gives them.

Return only the JSON object described by OUTPUT_SCHEMA_JSON.
