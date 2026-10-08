# Where Greeo's news comes from

Greeo retells news from free-to-read publishers. Every story credits its publishers by
name, and the Sources layer ("who reported this?") lists each article with its date
and link.

| Publisher | Feed | Coverage | Status |
| --- | --- | --- | --- |
| BBC News | [Africa](https://feeds.bbci.co.uk/news/world/africa/rss.xml) | Africa | Active |
| Al Jazeera | [All news](https://www.aljazeera.com/xml/rss/all.xml) | World | Active |
| The Guardian | [Africa](https://www.theguardian.com/world/africa/rss) | Africa | Active |
| DW | [Africa](https://rss.dw.com/rdf/rss-en-africa) | Africa | Active |
| Africanews | [RSS](https://www.africanews.com/feed/rss) | Africa | Off until its terms are confirmed |
| France 24 | [Africa](https://www.france24.com/en/africa/rss) | Africa | Off until its terms are confirmed |

The configuration lives in [`data/sources.yaml`](../data/sources.yaml) and is loaded with
`python manage.py load_sources /app/data/sources.yaml`.

## How Greeo uses them

- **What is stored:** headline, cleaned link (tracking parameters removed), publisher,
  date, and a snippet of at most 300 characters.
- **What is read but not stored:** the article's text, held in memory while the facts
  are established, then discarded. It is never spoken, shown or saved, and a check stops
  a tale from reusing the publisher's sentences.
- **Politeness:** an honest `GreeoBot` User-Agent with a contact address, `robots.txt`
  obeyed on every article, polling no more often than each feed's interval, and a stop
  on 403 or 429.
- **Paywalls:** only free-to-read publishers are used. Greeo never works around a paywall.

## Not used, and why

- **CNN:** its RSS feeds stopped updating in 2023.
- **NPR:** its `robots.txt` does not allow automated reading of articles, so Greeo does
  not read them.
