# Gmail for Jarvis

Jarvis uses your Gmail through Google's Gmail API with two scopes: `gmail.readonly` to read, and
`gmail.send` (added 2026-11-11) to send. Google enforces them: this connection cannot delete, label or
archive anything. Tokens are encrypted with Windows DPAPI in `data/gmail.enc` (only your Windows
account can decrypt them).

A sign-in made before 2026-11-11 can only read. To let Jarvis send, run
`.venv\Scripts\python.exe scripts\setup_gmail.py --renew` and approve both boxes in the browser. If Google
shows only the reading box, add the `gmail.send` scope under **Google Auth Platform → Data Access** first.

## One-time setup (about 10 minutes)

1. Go to <https://console.cloud.google.com/>, signed in as the Gmail account Jarvis should read.
   Create a project, e.g. "Jarvis".
2. **APIs & Services → Library**: search "Gmail API" and click **Enable**.
3. **Google Auth Platform → Branding** (or "OAuth consent screen"): app name "Jarvis", your email as
   support and developer contact. Audience: **External**.
4. **Audience**: add your Gmail address as a **test user** (wait for the save to finish).
   The app stays in "Testing": publishing needs a public home page and privacy policy. In
   Testing, Google expires the sign-in after 7 days. Jarvis says "Google sign-in for Gmail expired"
   when it's time; then run `.venv\Scripts\python.exe scripts\setup_gmail.py --renew` and approve
   in the browser (no JSON file needed).
5. **Clients → Create client**: type **Desktop app**, name "Jarvis". Download the JSON.
6. Run, with the path to that file:

   ```
   .venv\Scripts\python.exe scripts\setup_gmail.py "C:\Users\Lemab\Downloads\client_secret_....json"
   ```

   The browser opens Google's sign-in. Approve "View your email messages and settings" and
   "Send email on your behalf" (leave the second unticked to keep Jarvis read-only). The
   script prints the connected address and whether it can send. Delete the downloaded JSON afterwards; its contents are
   stored encrypted.

No restart is needed: the next time you ask, Jarvis uses it.

## What Jarvis does with it

- `check_email`: "any new email?", "did Sam reply?", Gmail searches like `from:sam newer_than:7d`.
- `read_email`: one message in full (long ones are cut at 6,000 characters).
- `send_email`: a new message or a reply in the same thread. Jarvis writes it, shows you the exact
  text (on screen and by Telegram), and sends only after your yes: spoken, the phone's Yes button,
  or a "yes" texted back.
- The daily review lists unread mail from the last day (no promotions/social) under
  "Email needing attention".

Email is written by other people, so Jarvis treats it as untrusted data: it summarizes and flags,
and never follows instructions or links inside a message.

## Disconnecting

Delete `data/gmail.enc`, and remove Jarvis's access at <https://myaccount.google.com/permissions>.
