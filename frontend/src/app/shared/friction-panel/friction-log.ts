// The friction log itself, bundled as text at build time: docs/FRICTION_LOG.md is the
// one source, so this panel and the written log never disagree.
import log from '../../../../../docs/FRICTION_LOG.md' with { loader: 'text' };

export const FRICTION_LOG_MARKDOWN: string = log;

/** A run of text, or a link when the log links to a doc. */
export interface Segment {
  text: string;
  href?: string;
}

export interface FrictionField {
  label: string;
  segments: Segment[];
}

export type FrictionGroup = 'Alexa+' | 'AWS' | 'MCP SDK' | 'Other';

export interface FrictionEntry {
  date: string;
  title: string;
  /** Critical, High, Medium or Low: the first word of the severity field. */
  severity: string;
  group: FrictionGroup;
  fields: FrictionField[];
}

const LINK = /\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g;

/** Read the log's entries (after "## Entries"), newest first. */
export function parseFrictionLog(markdown: string): FrictionEntry[] {
  const entries = markdown.split(/^## Entries\s*$/m)[1] ?? '';
  return entries
    .split(/^### /m)
    .slice(1)
    .map(parseEntry)
    .filter((entry): entry is FrictionEntry => entry !== null)
    .sort((a, b) => b.date.localeCompare(a.date));
}

function parseEntry(block: string): FrictionEntry | null {
  const [heading, ...lines] = block.trim().split('\n');
  const match = /^(\d{4}-\d{2}-\d{2}):\s*(.+)$/.exec(heading.trim());
  if (!match) {
    return null;
  }
  const fields: { label: string; text: string }[] = [];
  for (const line of lines) {
    const field = /^- \*\*(.+?):\*\*\s*(.*)$/.exec(line);
    if (field) {
      fields.push({ label: field[1], text: field[2] });
    } else if (line.trim() && fields.length) {
      fields.at(-1)!.text += ' ' + line.trim(); // a field's text continues on the next line
    }
  }
  const text = (label: string) => fields.find((f) => f.label === label)?.text ?? '';
  return {
    date: match[1],
    title: match[2].trim(),
    severity: /critical|high|medium|low/i.exec(text('Severity'))?.[0] ?? 'Unrated',
    group: groupOf(text('Tool / doc')),
    fields: fields.map((f) => ({ label: f.label, segments: segments(f.text) })),
  };
}

function groupOf(tool: string): FrictionGroup {
  if (/alexa/i.test(tool)) return 'Alexa+';
  if (/bedrock|polly|aws/i.test(tool)) return 'AWS';
  if (/sdk|mcp/i.test(tool)) return 'MCP SDK';
  return 'Other';
}

/** Plain text with links kept as links; markdown emphasis and code marks removed. */
export function segments(text: string): Segment[] {
  const plain = (value: string) => value.replace(/\*\*|`/g, '');
  const out: Segment[] = [];
  let last = 0;
  for (const link of text.matchAll(LINK)) {
    if (link.index > last) out.push({ text: plain(text.slice(last, link.index)) });
    out.push({ text: plain(link[1]), href: link[2] });
    last = link.index + link[0].length;
  }
  if (last < text.length) out.push({ text: plain(text.slice(last)) });
  return out;
}
