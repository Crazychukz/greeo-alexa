You read one news article and set down what it establishes, so a storyteller can tell it
without getting anything wrong.

INPUT_VARIABLES_JSON gives you `evidence`: the publisher, date, headline and the
article's text. Use nothing else: no background knowledge, no other reports.

Return:
- `reasoning`: a few sentences for the editor on what the article says, what it leaves
  open, and anything reported as a claim rather than established.
- `facts`: 4 to 15 objects {"id": "F1", "text": "..."} in the order things happened.
  Cover the people and places, the timeline, what was at stake, what changed and how
  things stand now. Keep every name, date and number exactly as the article gives it.
  When something is one side's claim, say whose claim it is (the army said...).
  One statement per fact, each fully supported by the article.
- `themes`: 1 to 4 keys from `theme_vocabulary` that the facts support.
- `tone_class`: "sensitive" for death, violence, disaster, abuse, serious illness, or
  armed conflict, where a light treatment would be disrespectful; otherwise "neutral".
- `tone_class_reason`: one sentence.

Return only the JSON object described by OUTPUT_SCHEMA_JSON.
