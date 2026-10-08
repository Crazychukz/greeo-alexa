/**
 * Split a reply into sentences for speech, as the contract asks: one /tts request per
 * sentence, so the first sentence plays while the next is fetched.
 *
 * Splits after . ! ? followed by a space. Decimal points and initials without a space
 * after them stay inside their sentence.
 */
export function splitSentences(spoken: string): string[] {
  return spoken
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}
