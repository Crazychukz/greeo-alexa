import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { Display, GreeoApi } from '../../core/api';
import { CardHost } from './card-host';

const FACTS: Display = {
  tool: 'get_facts',
  resource_uri: 'ui://greeo/facts',
  structured: {
    spoken: 'SYNTHETIC facts.',
    next_options: ['the sources'],
    story_id: 'st_1',
    title: 'SYNTHETIC EVENT',
    progress: { current: 'facts', steps: [] },
    facts: [{ text: 'SYNTHETIC fact.', sources: [] }],
  },
  is_error: false,
};

describe('CardHost', () => {
  it('answers the card handshake, sends the result, and passes chip taps on', async () => {
    TestBed.configureTestingModule({
      providers: [
        {
          provide: GreeoApi,
          useValue: {
            card: () =>
              of({
                uri: 'ui://greeo/facts',
                mime_type: 'text/html;profile=mcp-app',
                text: '<p>card</p>',
              }),
          },
        },
      ],
    });
    const fixture = TestBed.createComponent(CardHost);
    fixture.componentRef.setInput('display', FACTS);
    fixture.componentRef.setInput('spoken', 'SYNTHETIC facts.');
    const chips: string[] = [];
    fixture.componentInstance.chip.subscribe((text) => chips.push(text));
    await fixture.whenStable();

    const frame = (fixture.nativeElement as HTMLElement).querySelector('iframe')!;
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
    const card = frame.contentWindow!;
    const sent: {
      method?: string;
      id?: number;
      result?: { hostContext?: unknown };
      params?: unknown;
    }[] = [];
    card.postMessage = ((message: never) => sent.push(message)) as never;
    const fromCard = (data: object) =>
      window.dispatchEvent(
        new MessageEvent('message', { data: { jsonrpc: '2.0', ...data }, source: card }),
      );

    fromCard({ id: 1, method: 'ui/initialize', params: {} });
    expect(sent[0]).toMatchObject({ id: 1, result: { protocolVersion: '2026-01-26' } });
    expect(sent[0].result?.hostContext).toMatchObject({ theme: 'dark', displayMode: 'inline' });

    fromCard({ method: 'ui/notifications/initialized' });
    expect(sent.map((m) => m.method)).toEqual([
      undefined,
      'ui/notifications/tool-input',
      'ui/notifications/tool-result',
    ]);
    expect(sent[2].params).toMatchObject({
      structuredContent: FACTS.structured,
      isError: false,
      content: [{ type: 'text', text: 'SYNTHETIC facts.' }],
    });

    fromCard({
      id: 2,
      method: 'ui/message',
      params: { role: 'user', content: { type: 'text', text: 'the sources' } },
    });
    expect(sent.at(-1)).toMatchObject({ id: 2, result: {} });
    expect(chips).toEqual(['the sources']);

    // Messages from anywhere but the card are ignored.
    window.dispatchEvent(
      new MessageEvent('message', { data: { jsonrpc: '2.0', id: 9, method: 'ui/message' } }),
    );
    expect(chips).toEqual(['the sources']);
  });
});
