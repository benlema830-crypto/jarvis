"""Record your voice so Jarvis only responds to you. Run via enroll.bat."""

import os

import numpy as np
import speech_recognition as sr

from ears import SAMPLE_RATE, VOICEPRINT_PATH, SpeakerCheck

PHRASES = [
    "Jarvis, what's on my schedule for tomorrow?",
    "Good morning Jarvis, give me a quick status report.",
    "Open YouTube and search for the latest engineering videos.",
    "How is the weather looking this afternoon?",
    "Remind me what I was working on last night.",
    "The quick brown fox jumps over the lazy dog, then takes a nap in the sun.",
    "Jarvis, run a full diagnostic and tell me if anything looks unusual.",
    "I'd like a coffee, some music, and absolutely no meetings today.",
]


def main():
    print("=== Jarvis voice enrollment ===")
    print("Read each line out loud in your normal speaking voice.")
    print("Use the same mic and room you'll normally use Jarvis in.\n")

    checker = SpeakerCheck()
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 1.0
    embeddings = []

    with sr.Microphone(sample_rate=SAMPLE_RATE) as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)
        for i, phrase in enumerate(PHRASES, 1):
            while True:
                input(f"[{i}/{len(PHRASES)}] Press Enter, then say:\n    \"{phrase}\"")
                print("    listening...")
                try:
                    audio = recognizer.listen(source, timeout=6, phrase_time_limit=12)
                except sr.WaitTimeoutError:
                    print("    Didn't hear anything - try again.")
                    continue
                emb = checker.embed(audio)
                if emb is None:
                    print("    That was too short - try again.")
                    continue
                embeddings.append(emb)
                print("    Got it.\n")
                break

    embeddings = np.array(embeddings)
    voiceprint = embeddings.mean(axis=0)
    voiceprint /= np.linalg.norm(voiceprint)

    # How closely does each recording match the others? Sets a threshold that
    # lets your own voice through with some margin.
    scores = []
    for i in range(len(embeddings)):
        others = np.delete(embeddings, i, axis=0).mean(axis=0)
        others /= np.linalg.norm(others)
        scores.append(float(np.dot(embeddings[i], others)))
    threshold = float(np.clip(min(scores) - 0.07, 0.60, 0.82))

    os.makedirs(os.path.dirname(VOICEPRINT_PATH), exist_ok=True)
    np.savez(VOICEPRINT_PATH, embedding=voiceprint, threshold=threshold)

    print(f"Your self-match scores: {', '.join(f'{s:.2f}' for s in scores)}")
    print(f"Match threshold set to {threshold:.2f}")
    print("\nDone! Jarvis will now only respond to your voice.")
    print("If it ignores you too often, lower VOICE_MATCH_THRESHOLD in .env (e.g. 0.65).")
    print("If it responds to other people, raise it (e.g. 0.80).")


if __name__ == "__main__":
    main()
