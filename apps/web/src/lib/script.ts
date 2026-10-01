/**
 * Work out what language a reply is actually written in, from its script.
 *
 * The language picker says what the farmer chose for the interface. It does
 * not say what language the reply came back in, and those two part company
 * constantly: someone leaves the picker on English, types a question in
 * Punjabi, and Saathi answers in Punjabi because that is the language it was
 * asked in.
 *
 * Reading the picker instead of the text is what produced the worst bug this
 * interface has had. A Punjabi reply was read aloud by an English voice,
 * which cannot pronounce Gurmukhi and does not say so -- it discards every
 * character it has no phoneme for and reads whatever ASCII is left. A four
 * paragraph answer about stubble management came out of the speaker as
 * "twenty, comma, question mark". For a farmer using audio because they
 * cannot read, that is not a degraded answer, it is a wrong one delivered
 * confidently.
 *
 * Script is a far better signal than the picker because it is a property of
 * the thing being spoken. It cannot separate languages that share a script
 * -- Hindi and Marathi are both Devanagari -- so for those the picker breaks
 * the tie, which is the one job it is reliable for.
 */

interface Script {
  pattern: RegExp
  /** Languages written in this script, most common first. */
  languages: string[]
}

const SCRIPTS: Script[] = [
  { pattern: /[਀-੿]/g, languages: ['pa'] },        // Gurmukhi
  { pattern: /[ऀ-ॿ]/g, languages: ['hi', 'mr'] },  // Devanagari
  { pattern: /[ঀ-৿]/g, languages: ['bn', 'as'] },  // Bengali
  { pattern: /[઀-૿]/g, languages: ['gu'] },        // Gujarati
  { pattern: /[଀-୿]/g, languages: ['or'] },        // Odia
  { pattern: /[஀-௿]/g, languages: ['ta'] },        // Tamil
  { pattern: /[ఀ-౿]/g, languages: ['te'] },        // Telugu
  { pattern: /[ಀ-೿]/g, languages: ['kn'] },        // Kannada
  { pattern: /[ഀ-ൿ]/g, languages: ['ml'] },        // Malayalam
  { pattern: /[؀-ۿ]/g, languages: ['ar', 'fa'] },  // Arabic
  { pattern: /[ሀ-፿]/g, languages: ['am'] },        // Ethiopic
  { pattern: /[Ѐ-ӿ]/g, languages: ['ru'] },        // Cyrillic
  { pattern: /[一-鿿]/g, languages: ['zh'] },        // Han
]

const LATIN = /[A-Za-z]/g

function count(text: string, pattern: RegExp): number {
  return (text.match(pattern) || []).length
}

/**
 * The language a reply should be spoken in.
 *
 * Returns the interface language unless the text itself says otherwise. A
 * reply has to be *mostly* in another script before it overrides the picker,
 * so a stray Devanagari crop name inside an English paragraph does not throw
 * the whole thing onto a Hindi voice.
 *
 * Languages written in Latin script -- English, Spanish, Swahili and the
 * rest -- carry no script signal at all, so for those the picker is the only
 * evidence there is and it is used unchanged.
 */
export function speechLanguage(text: string, uiLanguage: string): string {
  let best: Script | null = null
  let bestCount = 0
  for (const script of SCRIPTS) {
    const n = count(text, script.pattern)
    if (n > bestCount) {
      bestCount = n
      best = script
    }
  }
  // No non-Latin script present, or not enough of one to outweigh the Latin
  // text around it. Either way the picker is the better guide.
  if (!best || bestCount <= count(text, LATIN)) return uiLanguage
  // Hindi and Marathi, or Bengali and Assamese, look identical here. If the
  // farmer picked one of them, believe them.
  return best.languages.includes(uiLanguage) ? uiLanguage : best.languages[0]
}
