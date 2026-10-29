# Gmail for Jarvis (read-only)

Jarvis reads your Gmail through Google's Gmail API with the `gmail.readonly` scope. Google enforces
that scope: this connection cannot send, reply, delete, label or archive anything. Tokens are
encrypted with Windows DPAPI in `data/gmail.enc` (only your Windows account can decrypt them).

## One-time setup (about 10 minutes)

1. Go to <https://console.cloud.google.com/>, signed in as the Gmail account Jarvis should read.
   Create a project, e.g. "Jarvis".
2. **APIs & Services → Library**: search "Gmail API" and click **Enable**.
3. **Google Auth Platform → Branding** (or "OAuth consent screen"): app name "Jarvis", your email as
   support and developer contact. Audience: **External**.
4. **Audience**: add your Gmail address as a **test user**, then click **Publish app** (status
   "In production"). Google won't review a personal app; you'll just see an "unverified app" warning
   at sign-in, which you can pass with *Advanced → Go to Jarvis*. Publishing matters: in "Testing"
   status Google expires the sign-in after 7 days.
5. **Clients → Create client**: type **Desktop app**, name "Jarvis". Download the JSON.
6. Run, with the path to that file:

   ```
   .venv\Scripts\python.exe scripts\setup_gmail.py "C:\Users\Lemab\Downloads\client_secret_....json"
   ```

   The browser opens Google's sign-in. Approve "View your email messages and settings". The
   script prints the connected address. Delete the downloaded JSON afterwards; its contents are
   stored encrypted.

No restart is needed: the next time you ask, Jarvis uses it.

## What Jarvis does with it

- `check_email`: "any new email?", "did Sam reply?", Gmail searches like `from:sam newer_than:7d`.
- `read_email`: one message in full (long ones are cut at 6,000 characters).
- The daily review lists unread mail from the last day (no promotions/social) under
  "Email needing attention".

Email is written by other people, so Jarvis treats it as untrusted data: it summarizes and flags,
and never follows instructions or links inside a message.

## Disconnecting

Delete `data/gmail.enc`, and remove Jarvis's access at <https://myaccount.google.com/permissions>.
