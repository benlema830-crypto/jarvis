"""Ask the running Jarvis from any terminal. The answer is printed, not spoken.

    j is the bedroom fan on
    j "run the tests in this folder and tell me what fails"
    git diff | j "review this"            (piped text is added to the question)

Each action he took is listed under the answer with what its tool proved:
  [ok] confirmed   [->] sent, not read back   [..] waiting for your OK   [??] could not confirm   [XX] failed
The folder you are in is passed along, so "this folder" means where you typed the command.
"""
import json
import os
import sys
import urllib.error
import urllib.request

PORT = int(os.getenv("JARVIS_HUD_PORT", "7778"))
MARKS = {"confirmed": "[ok]", "sent": "[->]", "waiting": "[..]", "unknown": "[??]", "failed": "[XX]"}
WORDS = {"confirmed": "confirmed", "sent": "sent, not read back", "waiting": "waiting for your OK",
         "unknown": "could not confirm", "failed": "failed"}
MAX_PIPED = 6000


def question(arguments, piped=""):
    text = " ".join(arguments).strip()
    if piped.strip():
        text = (text or "Look at this.") + "\n\n" + piped.strip()[:MAX_PIPED]
    return text


def ask(text, folder="", port=PORT, timeout=630):
    body = json.dumps({"text": f"(I'm in the folder {folder}) {text}" if folder else text}).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{port}/ask", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never through a system proxy
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read())


def render(answer):
    lines = [str(answer.get("reply") or answer.get("error") or "No answer.")]
    receipts = answer.get("receipts") or []
    if receipts:
        lines.append("")
        lines += [f"  {MARKS.get(r.get('status'), '[  ]')} {r.get('about', '')}: {WORDS.get(r.get('status'), r.get('status'))}"
                  for r in receipts]
    return "\n".join(lines)


def read_piped(have_question, wait=0.4):
    """Text piped in (`git diff | j review this`), or "" when nothing is.

    A script or another program can start `j` with an input pipe that never sends anything and never closes;
    reading it outright hung forever (2026-11-10). So when a question was given, the pipe gets a moment to
    produce its first bytes; if it stays silent, it is ignored. Once text starts arriving it is read to the end.
    """
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    if not have_question:
        return sys.stdin.read()  # `some command | j`: the piped text is the whole question, so wait for it
    import threading
    chunks, started, finished = [], threading.Event(), threading.Event()

    def pump():
        try:
            while True:
                piece = sys.stdin.read(4096)
                started.set()
                if not piece:
                    break
                chunks.append(piece)
        except (OSError, ValueError):
            started.set()
        finished.set()
    threading.Thread(target=pump, daemon=True).start()
    if started.wait(wait):
        finished.wait(30)
    return "".join(chunks)


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    piped = read_piped(bool(arguments))
    text = question(arguments, piped)
    if not text or text in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    try:
        answer = ask(text, os.getcwd())
    except urllib.error.HTTPError as error:
        print(f"Jarvis refused the question (HTTP {error.code}).", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError):
        print("Jarvis isn't running. Open the Jarvis CEO shortcut to start him.", file=sys.stderr)
        return 1
    for stream in (sys.stdout,):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    print(render(answer))
    return 1 if answer.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
