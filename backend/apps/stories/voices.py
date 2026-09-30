"""Storyteller voices and the shape of a tale.

A listener chooses a tone (light, balanced, serious). A voice is how a telling in that
tone is written and paced. The five voices come from the first Greeo prototype's
personas; their constraints are new. Voices shape wording and rhythm only: no voice may
add facts, use dialect, or judge a real person or side (see AGENTS.md rules 3, 4, 13).
"""

from __future__ import annotations

from dataclasses import dataclass

SENSITIVE = "sensitive"


@dataclass(frozen=True)
class VoiceStyle:
    key: str
    name: str
    style: str
    tones: tuple[str, ...]
    sensitive_ok: bool
    # Speech pacing for hosts that synthesise audio: percent of normal rate, and pauses.
    rate_percent: int
    sentence_pause_ms: int
    comma_pause_ms: int


VOICE_STYLES: dict[str, VoiceStyle] = {
    voice.key: voice
    for voice in (
        VoiceStyle(
            key="moonlight_elder",
            name="Moonlight Elder",
            style="Calm, slow and reflective. Simple sentences. Repetition. Gentle authority.",
            tones=("balanced", "serious"),
            sensitive_ok=True,
            rate_percent=88,
            sentence_pause_ms=360,
            comma_pause_ms=120,
        ),
        VoiceStyle(
            key="village_fire",
            name="Village Fire Storyteller",
            style="Animated but controlled. Vivid imagery. Strong rhythm and pacing. Respectful.",
            tones=("light", "balanced"),
            sensitive_ok=False,
            rate_percent=97,
            sentence_pause_ms=240,
            comma_pause_ms=100,
        ),
        VoiceStyle(
            key="wise_judge",
            name="Wise Judge",
            style=(
                "Firm and measured. Sets out cause and consequence plainly. Weighs what "
                "happened; never rules on who is right."
            ),
            tones=("serious",),
            sensitive_ok=False,
            rate_percent=92,
            sentence_pause_ms=300,
            comma_pause_ms=110,
        ),
        VoiceStyle(
            key="hopeful_healer",
            name="Hopeful Healer",
            style="Compassionate and soothing. Gentle optimism. Dwells on resilience and care.",
            tones=("balanced", "serious"),
            sensitive_ok=True,
            rate_percent=93,
            sentence_pause_ms=270,
            comma_pause_ms=110,
        ),
        VoiceStyle(
            key="playful_trickster",
            name="Playful Trickster",
            style="Light humour and witty wisdom. Gentle teasing of situations, never of people.",
            tones=("light",),
            sensitive_ok=False,
            rate_percent=100,
            sentence_pause_ms=220,
            comma_pause_ms=90,
        ),
    )
}

# The default voice per tone, for neutral and for sensitive stories. Sensitive stories
# have no light telling, so there is no entry for it.
DEFAULT_VOICE = {
    ("light", False): "playful_trickster",
    ("balanced", False): "moonlight_elder",
    ("serious", False): "wise_judge",
    ("balanced", True): "moonlight_elder",
    ("serious", True): "hopeful_healer",
}


def voice_problems(voice_key: str, tone: str, tone_class: str) -> list[str]:
    """Why a voice cannot tell this tone of this story; empty when it can."""
    voice = VOICE_STYLES.get(voice_key)
    if voice is None:
        return [f"unknown voice {voice_key!r}; choose one of {', '.join(VOICE_STYLES)}."]
    problems = []
    if tone not in voice.tones:
        problems.append(f"the {voice.name} voice is not used for a {tone} telling.")
    if tone_class == SENSITIVE and not voice.sensitive_ok:
        problems.append(f"the {voice.name} voice is not used on sensitive stories.")
    return problems


def voice_for(tone: str, tone_class: str, requested: str | None = None) -> VoiceStyle:
    """The requested voice when it fits, otherwise the default for this tone and story."""
    if requested and not voice_problems(requested, tone, tone_class):
        return VOICE_STYLES[requested]
    key = DEFAULT_VOICE.get((tone, tone_class == SENSITIVE), "moonlight_elder")
    return VOICE_STYLES[key]


# The shape of a tale, from the prototype's story prompt (protagonists, conflict, turning
# point, resolution, moral), mapped onto 3-5 beats. The moral is the separate closing.
BEAT_ROLES = {
    3: ("opening", "trouble and turning point", "resolution"),
    4: ("opening", "trouble", "turning point", "resolution"),
    5: ("opening", "trouble", "the struggle", "turning point", "resolution"),
}
ROLE_GUIDANCE = {
    "opening": "Who and where: the people and the place, as the facts give them.",
    "trouble": "What stood in the way, or what was at stake.",
    "the struggle": "What people did about it, step by step.",
    "turning point": "The moment things changed.",
    "trouble and turning point": "What stood in the way, and the moment things changed.",
    "resolution": "How it stands now, according to the facts. No invented ending.",
}


def beat_roles(count: int) -> tuple[str, ...]:
    """The role of each beat for a tale of this length (3 to 5 beats)."""
    return BEAT_ROLES.get(count, BEAT_ROLES[4])
