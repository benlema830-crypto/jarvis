"""The language Jarvis answers in.

"Jarvis, answer me in Spanish" sets it; "back to English" clears it. The owner goes on speaking English (speech
recognition, the wake word and "stop" stay English). Jarvis writes and speaks his replies in the chosen language
until told otherwise, including what he reports from tools.

Two things change: a line in the brain's instructions, and the language given to the voice engine.
Checked on this PC on 2026-11-11 with the VoiceStudio cloned voice, by transcribing its speech back with
Whisper: Spanish, German, French and Hindi came back word for word. Japanese was right only when the engine
was left to detect the language itself, so a language code is sent only for the four that were checked with one.
Other languages are passed through unchecked and the tool says so.

The honesty checks that read Jarvis's wording ("I've turned it off") only understand English, so in another
language they don't fire. The receipts beside each reply still show what every tool did.

Saved as preferences "reply_language": {"code": "es", "name": "Spanish"}; absent means English.
"""
import preferences

LANGUAGES = {
    "en": ("English", "english"), "es": ("Spanish", "spanish", "español", "espanol", "castellano"),
    "de": ("German", "german", "deutsch"), "fr": ("French", "french", "français", "francais"),
    "hi": ("Hindi", "hindi"), "it": ("Italian", "italian", "italiano"),
    "pt": ("Portuguese", "portuguese", "português", "portugues", "brazilian portuguese"),
    "nl": ("Dutch", "dutch", "nederlands"), "ja": ("Japanese", "japanese"), "ko": ("Korean", "korean"),
    "zh": ("Chinese", "chinese", "mandarin"), "ar": ("Arabic", "arabic"), "ru": ("Russian", "russian"),
    "tr": ("Turkish", "turkish"), "pl": ("Polish", "polish"), "sv": ("Swedish", "swedish"),
    "uk": ("Ukrainian", "ukrainian"), "el": ("Greek", "greek"), "he": ("Hebrew", "hebrew"),
    "vi": ("Vietnamese", "vietnamese"), "id": ("Indonesian", "indonesian"), "th": ("Thai", "thai"),
    "fa": ("Dari", "dari", "farsi", "persian"), "ur": ("Urdu", "urdu"), "bn": ("Bengali", "bengali"),
}
CHECKED = {"es", "de", "fr", "hi"}   # spoken by the VoiceStudio voice and transcribed back correctly, with the code sent
# The local Qwen voice takes a language by name and knows only these.
QWEN = {"zh": "Chinese", "en": "English", "ja": "Japanese", "ko": "Korean", "de": "German", "fr": "French",
        "ru": "Russian", "pt": "Portuguese", "es": "Spanish", "it": "Italian"}


def find(said):
    """The language code for what the owner called it ("Spanish", "español", "es"), or None."""
    said = " ".join(str(said or "").casefold().split())
    for code, names in LANGUAGES.items():
        if said == code or said in (name.casefold() for name in names):
            return code
    return None


def code():
    """"" for English, otherwise the saved language's code."""
    value = preferences.read().get("reply_language")
    saved = value.get("code") if isinstance(value, dict) else None
    return saved if saved in LANGUAGES and saved != "en" else ""


def name(language=None):
    language = code() if language is None else language
    return LANGUAGES[language][0] if language in LANGUAGES else "English"


def choose(said):
    """Save the language and return its code ("" for English). Raises ValueError for one that isn't listed."""
    found = find(said)
    if found is None:
        raise ValueError(f"I don't have '{said}' as a reply language. I can answer in: "
                         + ", ".join(names[0] for names in LANGUAGES.values()) + ".")
    if found == "en":
        preferences.update(reply_language=None)
        return ""
    preferences.update(reply_language={"code": found, "name": LANGUAGES[found][0]})
    return found


def prompt(language=None):
    """The line added to the brain's instructions; empty for English."""
    language = code() if language is None else language
    if not language:
        return ""
    return (f"\n\nReply language: {name(language)}. The user speaks to you in English and understands it, but they "
            f"have asked you to answer in {name(language)}. Write and say every reply in {name(language)}, including "
            "what you report from tools and your short confirmations, until they tell you to switch back "
            "(reply_language). Keep names, file paths, code and quoted text as they are. Tool calls, notes you save "
            "and text you send elsewhere stay in English unless asked.")


def voice_code(language=None):
    """The code to hand the VoiceStudio engine, or None to let it detect the language from the text."""
    language = code() if language is None else language
    return language if language in CHECKED else None
