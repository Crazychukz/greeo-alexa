import { Injectable, computed, signal } from '@angular/core';

/** Who is listening, as the backend sees it. */
export type Listener =
  | { kind: 'guest' }
  /** A demo token from `manage.py create_demo_user`. */
  | { kind: 'token'; token: string }
  /** Local development only: the backend honours it only with DEBUG on. */
  | { kind: 'dev'; name: string };

const STORAGE_KEY = 'greeo.listener';
const SESSION_ID = /^[A-Za-z0-9_-]{1,64}$/;

/**
 * The listener and the current conversation.
 *
 * A session is one conversation (the backend keeps its context for 30 minutes); the
 * listener's own memory (saves, progress) lives on the server and outlives sessions.
 * The listener is kept in sessionStorage so a reload keeps you signed in, but closing
 * the tab forgets the token. Storage can be unavailable, so every access is guarded.
 */
@Injectable({ providedIn: 'root' })
export class ListenerSession {
  private readonly listenerState = signal<Listener>(readStoredListener());
  private readonly sessionState = signal<string>(newSessionId());

  readonly listener = this.listenerState.asReadonly();
  readonly sessionId = this.sessionState.asReadonly();
  readonly isGuest = computed(() => this.listenerState().kind === 'guest');

  /** The headers that tell the backend who is listening; none for a guest. */
  readonly headers = computed((): Record<string, string> => listenerHeaders(this.listenerState()));

  signIn(listener: Listener): void {
    this.listenerState.set(normalise(listener));
    storeListener(this.listenerState());
  }

  signOut(): void {
    this.signIn({ kind: 'guest' });
  }

  /** Start a fresh conversation, as after "start over". */
  newConversation(): string {
    this.sessionState.set(newSessionId());
    return this.sessionState();
  }
}

export function listenerHeaders(listener: Listener): Record<string, string> {
  const headers: Record<string, string> = {};
  if (listener.kind === 'token') {
    headers['Authorization'] = `Bearer ${listener.token}`;
  } else if (listener.kind === 'dev') {
    headers['X-Greeo-User'] = listener.name;
  }
  return headers;
}

export function newSessionId(): string {
  const id = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`.replace('.', '');
  return SESSION_ID.test(id) ? id : id.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 64);
}

function normalise(listener: Listener): Listener {
  if (listener.kind === 'token' && listener.token.trim()) {
    return { kind: 'token', token: listener.token.trim() };
  }
  if (listener.kind === 'dev' && listener.name.trim()) {
    return { kind: 'dev', name: listener.name.trim() };
  }
  return { kind: 'guest' };
}

function readStoredListener(): Listener {
  try {
    const raw = globalThis.sessionStorage?.getItem(STORAGE_KEY);
    return raw ? normalise(JSON.parse(raw) as Listener) : { kind: 'guest' };
  } catch {
    return { kind: 'guest' };
  }
}

function storeListener(listener: Listener): void {
  try {
    globalThis.sessionStorage?.setItem(STORAGE_KEY, JSON.stringify(listener));
  } catch {
    // Private windows and blocked storage: the listener lasts until reload instead.
  }
}
