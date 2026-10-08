import { FRICTION_LOG_MARKDOWN, parseFrictionLog, segments } from './friction-log';

const LOG = `# Friction log

## Entry template

### YYYY-MM-DD: Short title

- **Severity:** Critical | High | Medium | Low

## Entries

### 2026-09-28: Older entry

- **Tool / doc:** Alexa+ MCP Toolkit,
  [Overview](https://developer.amazon.com/overview.html)
- **Severity:** Medium

### 2026-10-07: Newer entry

- **Tool / doc:** Amazon Polly \`SynthesizeSpeech\`
- **Severity:** High for voice products; Medium otherwise.
`;

describe('parseFrictionLog', () => {
  it('reads entries newest first, skipping the template, and groups them by tool', () => {
    const entries = parseFrictionLog(LOG);
    expect(entries.map((e) => [e.date, e.title, e.group, e.severity])).toEqual([
      ['2026-10-07', 'Newer entry', 'AWS', 'High'],
      ['2026-09-28', 'Older entry', 'Alexa+', 'Medium'],
    ]);
  });

  it('joins a field that continues on the next line and keeps its links', () => {
    const tool = parseFrictionLog(LOG)[1].fields[0];
    expect(tool.segments).toEqual([
      { text: 'Alexa+ MCP Toolkit, ' },
      { text: 'Overview', href: 'https://developer.amazon.com/overview.html' },
    ]);
  });

  it('drops markdown marks and keeps only https links', () => {
    expect(segments('**bold** `code` [x](javascript:alert(1))')).toEqual([
      { text: 'bold code [x](javascript:alert(1))' },
    ]);
  });

  it('reads the real log in docs/FRICTION_LOG.md', () => {
    const entries = parseFrictionLog(FRICTION_LOG_MARKDOWN);
    expect(entries.length).toBeGreaterThanOrEqual(7);
    expect(entries.every((e) => e.fields.length >= 8)).toBe(true);
  });
});
