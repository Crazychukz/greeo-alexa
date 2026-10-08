import { WELCOME, headingFor } from './listen';

describe('headingFor', () => {
  it('welcomes when Greeo has said nothing yet', () => {
    expect(headingFor('', false)).toBe(WELCOME);
  });

  it('shows a whole reply that has no card', () => {
    const reply = "Here are today's stories. Which one would you like to hear?";
    expect(headingFor(reply, false)).toBe(reply);
  });

  it('leads into a card with its first sentence only', () => {
    expect(headingFor('Come close, come close. In Veloria the river ran wide.', true)).toBe(
      'Come close, come close.',
    );
  });

  it('cuts a long first sentence to about a line and a half', () => {
    const long = Array.from({ length: 30 }, (_, i) => `word${i}`).join(' ') + '.';
    const heading = headingFor(long, true);
    expect(heading.split(' ')).toHaveLength(16);
    expect(heading.endsWith('…')).toBe(true);
  });

  it('above story tiles, keeps the intro and the question, not the titles', () => {
    const listing =
      "Here are today's stories: SYNTHETIC one. SYNTHETIC two. Which one would you like to hear?";
    expect(headingFor(listing, false, true)).toBe(
      "Here are today's stories. Which one would you like to hear?",
    );
  });
});

describe('Listen account linking', () => {
  it('links and unlinks the simulated household listener', async () => {
    const { TestBed } = await import('@angular/core/testing');
    const { ListenerSession, listenerHeaders } = await import('../../core/api');
    const { DEMO_LISTENER } = await import('./listen');
    sessionStorage.clear();
    const session = TestBed.inject(ListenerSession);

    session.signIn({ kind: 'dev', name: DEMO_LISTENER });
    expect(session.isGuest()).toBe(false);
    expect(listenerHeaders(session.listener())).toEqual({ 'X-Greeo-User': DEMO_LISTENER });

    session.signOut();
    expect(session.isGuest()).toBe(true);
  });
});
