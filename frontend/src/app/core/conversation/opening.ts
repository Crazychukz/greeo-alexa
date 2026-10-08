import { Router } from '@angular/router';

/**
 * What another page asks the listening screen to say first: typed or spoken words, or a
 * tapped story. The conversation belongs to the listening screen and ends when it is left,
 * so a page starts one by passing its opening along with the navigation.
 */
export interface Opening {
  text: string;
  /** Set when a story was tapped: it is told directly, with no model asked. */
  storyId?: string;
}

/** Open the listening screen and have it say this first. */
export function openListen(router: Router, opening: Opening): Promise<boolean> {
  return router.navigate(['/listen'], { state: { opening } });
}

/**
 * The opening passed with the navigation in progress, if any (call while it runs). Back
 * and forward replay history, not a request: they open the screen fresh, saying nothing.
 */
export function currentOpening(router: Router): Opening | null {
  const navigation = router.currentNavigation();
  if (!navigation || navigation.trigger === 'popstate') {
    return null;
  }
  const state = navigation.extras.state as { opening?: Opening } | undefined;
  const opening = state?.opening;
  return opening && typeof opening.text === 'string' && opening.text.trim() ? opening : null;
}
