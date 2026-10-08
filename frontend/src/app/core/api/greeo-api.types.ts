/**
 * Types for the Greeo simulator API, mirroring docs/FRONTEND_API.md.
 *
 * The backend's tool results are the source of truth; when a shape changes there,
 * change it here and in the contract together.
 */

// Requests ---------------------------------------------------------------------------

export interface TurnRequest {
  session_id: string;
  /** What the listener said or typed, or a chip's label. 1-500 characters. */
  text: string;
  /** Set when the listener tapped a story on screen: that story is told directly. */
  story_id?: string;
  /** With story_id: Greeo carrying on by itself, so no model is asked what comes next. */
  follow_up?: FollowUp;
}

/** What Greeo says next on its own: the next part of the tale, or its closing thought. */
export type FollowUp = 'next_beat' | 'closing';

export interface ResetRequest {
  session_id: string;
}

export interface TtsRequest {
  /** One sentence, at most 600 characters. */
  text: string;
  /** The storyteller voice, from TaleBeat.voice_style, so pacing matches. */
  voice?: string;
}

// Turn response ----------------------------------------------------------------------

/** Who chose the tools: a model, the scripted router, or the listener tapping a story. */
export type HostMode = 'mock' | 'llm' | 'strands' | 'tap' | 'auto';

export type ToolName =
  | 'search_events'
  | 'get_briefing'
  | 'tell_tale'
  | 'get_moral'
  | 'explain_proverb'
  | 'get_facts'
  | 'get_context'
  | 'get_perspectives'
  | 'get_sources'
  | 'save_for_later'
  | 'get_saved_stories'
  | 'set_preferences';

export type CardUri =
  | 'ui://greeo/tale'
  | 'ui://greeo/wisdom'
  | 'ui://greeo/facts'
  | 'ui://greeo/context'
  | 'ui://greeo/perspectives'
  | 'ui://greeo/sources';

export interface ToolTraceStep {
  tool: ToolName;
  args: Record<string, unknown>;
  ms: number;
  ok: boolean;
}

/** The last tool's result. `{}` when no tool ran (help text, sign-in problems). */
export interface Display {
  tool: ToolName;
  /** The card for this result, or null: show a native view instead. Always null on error. */
  resource_uri: CardUri | null;
  structured: Structured;
  is_error: boolean;
}

export interface TurnResult {
  /** Exactly what to speak and show. Never empty, at most 75 words. */
  spoken: string;
  display: Display | Record<string, never>;
  tool_trace: ToolTraceStep[];
  host_mode: HostMode;
}

export function hasDisplay(turn: TurnResult): turn is TurnResult & { display: Display } {
  return 'tool' in turn.display;
}

// Structured results, by tool --------------------------------------------------------

export interface Envelope {
  spoken: string;
  /** Suggestion chips, at most five. */
  next_options: string[];
}

export type LayerKey =
  'tale' | 'closing' | 'proverbs' | 'facts' | 'context' | 'perspectives' | 'sources';

export interface LayerStep {
  key: LayerKey;
  label: string;
  state: 'current' | 'heard' | 'ahead';
}

export interface StoryEnvelope extends Envelope {
  story_id: string;
  title: string;
  progress: { current: LayerKey; steps: LayerStep[] };
}

export interface SourceRef {
  publisher: string;
  date: string;
}

export interface ProverbDetail {
  slot: string;
  spoken_form: string;
  original_text: string;
  language: string;
  culture: string;
  meaning: string;
  source_citation: string;
  verification_status: 'verified' | 'single_source';
}

export type Tone = 'light' | 'balanced' | 'serious';

export interface StoryListing {
  story_id: string;
  title: string;
  region: string;
}

/** search_events, get_briefing (no card). */
export interface StoryList extends Envelope {
  stories: StoryListing[];
  page: number;
  has_more: boolean;
}

/** tell_tale -> ui://greeo/tale */
export interface TaleBeat extends StoryEnvelope {
  beat: number;
  beats_total: number;
  has_more: boolean;
  tone_served: Tone;
  voice_style: string;
  voice_name: string;
  /** The beat exactly as written, proverbs included. */
  text: string;
  proverbs_used: { slot: string; culture: string; spoken_form: string }[];
}

/** get_moral -> ui://greeo/wisdom */
export interface ClosingThought extends StoryEnvelope {
  closing_kind: 'moral' | 'reflection' | 'none';
  text: string;
  proverb_note: string;
  proverbs: ProverbDetail[];
}

/** explain_proverb -> ui://greeo/wisdom */
export interface ProverbExplanation extends StoryEnvelope {
  proverbs: ProverbDetail[];
  has_proverb: boolean;
  which: number;
  proverbs_total: number;
  spoken_form: string;
  original_text: string;
  language: string;
  culture: string;
  meaning: string;
  source_citation: string;
  verification_status: string;
}

/** get_facts -> ui://greeo/facts */
export interface FactList extends StoryEnvelope {
  facts: { text: string; sources: SourceRef[] }[];
}

/** get_context -> ui://greeo/context */
export interface ContextList extends StoryEnvelope {
  context: {
    kind: 'background' | 'why_it_matters' | 'consequence';
    label: string;
    text: string;
    sources: SourceRef[];
  }[];
}

/** get_perspectives -> ui://greeo/perspectives */
export interface PerspectiveList extends StoryEnvelope {
  perspectives: { label: string; summary: string; sources: SourceRef[] }[];
}

/** get_sources -> ui://greeo/sources */
export interface SourceList extends StoryEnvelope {
  sources: {
    publisher: string;
    headline: string;
    date: string;
    supports: ('facts' | 'context' | 'perspectives')[];
    url: string | null;
  }[];
}

/** save_for_later (no card). */
export interface SaveResult extends Envelope {
  story_id: string;
  title: string;
  saved: boolean;
}

export interface SavedStory {
  story_id: string;
  title: string;
  saved: boolean;
  tone: string;
  last_beat: number;
  beats_total: number;
  tale_completed: boolean;
  resume_hint: string;
}

/** get_saved_stories (no card). */
export interface SavedList extends Envelope {
  stories: SavedStory[];
}

/** set_preferences (no card). */
export interface PreferencesResult extends Envelope {
  tone: string | null;
  regions: string[];
  topics: string[];
  reset: boolean;
}

export type FriendlyErrorCode =
  | 'no_results'
  | 'no_more_results'
  | 'unknown_story'
  | 'which_story'
  | 'beat_out_of_range'
  | 'tale_unavailable'
  | 'proverb_out_of_range'
  | 'proverb_unavailable'
  | 'needs_account'
  | 'nothing_to_change'
  | 'unknown_topic'
  | 'invalid_request'
  | 'unexpected';

/** Any tool, when display.is_error is true. Speak `spoken`; only needs_account needs UI. */
export interface FriendlyError extends Envelope {
  error: FriendlyErrorCode;
}

export type Structured =
  | StoryList
  | TaleBeat
  | ClosingThought
  | ProverbExplanation
  | FactList
  | ContextList
  | PerspectiveList
  | SourceList
  | SaveResult
  | SavedList
  | PreferencesResult
  | FriendlyError;

// Other endpoints --------------------------------------------------------------------

export interface CardResource {
  uri: CardUri;
  mime_type: 'text/html;profile=mcp-app';
  /** The card's complete HTML, for a sandboxed iframe's srcdoc. */
  text: string;
}

export interface ResetResult {
  reset: true;
}

/** Audio for one sentence, or null when the backend has no speech (use browser speech). */
export interface SpeechAudio {
  audio: Blob;
  /** Whether the backend served it from its speech cache. */
  cached: boolean;
}

/** A demo story on the home screen's Demo stories card. */
export interface DemoStory {
  story_id: string;
  title: string;
  region: string;
  /** The tones it can be told in, such as "balanced" and "light". */
  tones: string[];
}

/** GET /stories: the demo stories, and how many news stories are ready to tell. */
export interface StoryShelf {
  demo: DemoStory[];
  news_count: number;
}
