import {
  ChangeDetectionStrategy,
  Component,
  DOCUMENT,
  DestroyRef,
  ElementRef,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

import { CardUri, Display, GreeoApi } from '../../core/api';

const PROTOCOL_VERSION = '2026-01-26';

interface RpcMessage {
  jsonrpc: '2.0';
  id?: number | string;
  method?: string;
  params?: Record<string, unknown>;
  result?: unknown;
}

/**
 * The MCP Apps host for one card: Greeo's own card HTML, from the MCP server, in a
 * sandboxed iframe, spoken to over postMessage as the MCP Apps spec describes.
 *
 *   card -> ui/initialize            host -> result with hostContext (theme, size)
 *   card -> notifications/initialized host -> tool-input, then tool-result
 *   card -> ui/message (a chip)       host -> {} and emits the chip's words
 *
 * When the next result uses the same card, only a new tool-result is sent; a different
 * card is torn down (ui/resource-teardown) and replaced. The iframe has scripts but no
 * same-origin access, so a card can reach nothing but this host.
 */
@Component({
  selector: 'greeo-card-host',
  template: `
    @if (html(); as cardHtml) {
      <!-- The frame's colour scheme matches the card's theme; otherwise the browser paints
           an opaque backdrop behind the see-through card. -->
      <iframe
        #frame
        [srcdoc]="cardHtml"
        [style.color-scheme]="theme()"
        sandbox="allow-scripts"
        title="Greeo card"
      ></iframe>
    }
  `,
  styles: `
    :host {
      display: block;
      height: 100%;
    }
    iframe {
      display: block;
      width: 100%;
      height: 100%;
      border: 0;
      border-radius: 16px; // the card's own corners
      background: transparent;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CardHost {
  /** The latest result to show; its resource_uri picks the card. */
  readonly display = input.required<Display>();
  /** Greeo's words for this result, sent as the tool result's text content. */
  readonly spoken = input('');
  readonly theme = input<'dark' | 'light'>('dark');
  /** A chip was tapped in the card: its words, to send as the next thing said. */
  readonly chip = output<string>();

  private readonly api = inject(GreeoApi);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly window = inject(DOCUMENT).defaultView;
  private readonly frame = viewChild<ElementRef<HTMLIFrameElement>>('frame');

  protected readonly html = signal<SafeHtml | null>(null);
  private loadedUri: CardUri | null = null;
  private initialized = false;
  private nextId = 1;

  constructor() {
    const onMessage = (event: MessageEvent) => this.receive(event);
    this.window?.addEventListener('message', onMessage);
    inject(DestroyRef).onDestroy(() => this.window?.removeEventListener('message', onMessage));

    effect(() => {
      const display = this.display();
      untracked(() => this.show(display));
    });
  }

  private show(display: Display): void {
    const uri = display.resource_uri;
    if (!uri) {
      return;
    }
    if (uri === this.loadedUri) {
      if (this.initialized) {
        this.sendResult(display); // same card, new data: no reload
      }
      return;
    }
    this.teardown();
    this.loadedUri = uri;
    this.initialized = false;
    this.api.card(uri).subscribe({
      next: (card) => {
        if (this.loadedUri === uri) {
          // Safe to bypass: the HTML is Greeo's own card, isolated in a sandboxed iframe.
          this.html.set(this.sanitizer.bypassSecurityTrustHtml(card.text));
        }
      },
      error: () => this.html.set(null),
    });
  }

  private receive(event: MessageEvent): void {
    const frameWindow = this.frame()?.nativeElement.contentWindow;
    const message = event.data as RpcMessage;
    if (!frameWindow || event.source !== frameWindow || message?.jsonrpc !== '2.0') {
      return;
    }
    switch (message.method) {
      case 'ui/initialize':
        this.post({
          jsonrpc: '2.0',
          id: message.id,
          result: {
            protocolVersion: PROTOCOL_VERSION,
            hostInfo: { name: 'greeo-simulator', version: '1.0.0' },
            hostCapabilities: {},
            hostContext: this.hostContext(),
          },
        });
        break;
      case 'ui/notifications/initialized':
        this.initialized = true;
        this.post({
          jsonrpc: '2.0',
          method: 'ui/notifications/tool-input',
          params: { arguments: {} },
        });
        this.sendResult(this.display());
        break;
      case 'ui/message': {
        this.post({ jsonrpc: '2.0', id: message.id, result: {} });
        const content = message.params?.['content'] as { text?: string } | undefined;
        if (content?.text) {
          this.chip.emit(content.text);
        }
        break;
      }
      default:
        if (message.id !== undefined && message.method) {
          // A request this host does not support: answer so the card is never left waiting.
          this.post({ jsonrpc: '2.0', id: message.id, result: {} });
        }
    }
  }

  private sendResult(display: Display): void {
    this.post({
      jsonrpc: '2.0',
      method: 'ui/notifications/tool-result',
      params: {
        content: [{ type: 'text', text: this.spoken() || display.structured.spoken }],
        structuredContent: display.structured,
        isError: display.is_error,
      },
    });
  }

  private teardown(): void {
    if (this.initialized) {
      this.post({
        jsonrpc: '2.0',
        id: this.nextId++,
        method: 'ui/resource-teardown',
        params: { reason: 'next card' },
      });
    }
  }

  private hostContext(): Record<string, unknown> {
    // Layout size, not getBoundingClientRect: the tilted screen would report its projection.
    const frame = this.frame()?.nativeElement;
    const box = frame ? { width: frame.offsetWidth, height: frame.offsetHeight } : null;
    return {
      theme: this.theme(),
      displayMode: 'inline',
      availableDisplayModes: ['inline'],
      // A fixed height (not maxHeight): the card fills this frame exactly, scrolls its
      // text inside and keeps its buttons in view, instead of growing past the screen.
      containerDimensions: {
        width: Math.round(box?.width ?? 600),
        height: Math.round(box?.height ?? 400),
      },
      locale: this.window?.navigator.language ?? 'en-GB',
      platform: 'web',
    };
  }

  private post(message: RpcMessage): void {
    // The sandboxed card has an opaque origin, so '*' is the only target that reaches it;
    // the message carries nothing secret.
    this.frame()?.nativeElement.contentWindow?.postMessage(message, '*');
  }
}
