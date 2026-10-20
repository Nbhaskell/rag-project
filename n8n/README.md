# Connecting n8n

[n8n](https://n8n.io) is a tool for building automations by connecting boxes (called nodes) on a
screen. Here it runs on your own computer and uses this project through the JSON API described in
the main README, so something that happens elsewhere (a message, a form, a timer) can ask your
documents a question and send the answer on.

```
 something happens         n8n  (port 5678)                this project  (port 8000)
 (a message, a form,  ───►  trigger → steps  ───────────►  /api/ask      searches and answers
  a timer)                          ▲                      /api/reindex  updates the index
                                    └─── answer + sources ◄───────────────┘
```

n8n is free to run yourself for personal or internal use (its Sustainable Use License forbids
reselling it). It needs Node.js 24, which also needs to be on your computer.

## What is in this folder

| File | What it is |
|---|---|
| `ask-the-documents.json` | A ready-made workflow: a **Webhook** receives `{"question": "..."}`, an **HTTP Request** asks this project's `/api/ask`, and a **Respond to Webhook** sends the answer back |
| `add-documents.json` | A second ready-made workflow: an upload **form** where you pick a file, and n8n saves it into the project's `docs` folder (see "Add documents from a web form" below) |
| `start-n8n.ps1` | Starts n8n with private settings (only this computer can reach it; its usage reporting and update checks are off; its file nodes may only touch the `docs` folder) |

## Set it up

1. **Start the chat server, with a token.** The token is a shared password, so nothing else on
   the computer can use the API. In PowerShell, in the project folder:
   ```
   python -c "import secrets; print(secrets.token_urlsafe(24))"
   ```
   Copy the result, then (replacing the text in quotes) start the chat:
   ```
   $env:RAG_API_TOKEN = 'paste-your-token-here'
   python chat.py --no-browser
   ```
   Keep the token private; do not paste it into chat messages or commit it. The `$env:` line lasts
   only for that PowerShell window, so repeat it each time you start the chat.
2. **Start n8n**, in another PowerShell window, from the project folder:
   ```
   .\n8n\start-n8n.ps1
   ```
   The first run downloads n8n and can take several minutes. When it prints
   `Editor is now accessible via: http://127.0.0.1:5678`, open that address in your browser.
3. **Create your n8n account** on the first-run page. It is stored on your computer only. If it
   offers a licence key or product updates, you can skip them.
4. **Import the workflow.** Create a new workflow, open the **⋯** menu at the top right, choose
   **Import from File…** and pick `n8n\ask-the-documents.json`.
5. **Give n8n the token.** Double-click the **Ask the RAG project** box. Under **Header Auth**
   click **Connect to Header Auth** and create a credential with **Name** `X-API-Key` and **Value**
   your token. Save it, and close the box. (The workflow file only remembers that a credential
   exists, never the token, so you repeat this step on each new n8n installation.)
6. **Test it.** Click **Execute** on the canvas, then straight away run this in PowerShell:
   ```
   Invoke-RestMethod -Uri http://127.0.0.1:5678/webhook-test/ask-docs -Method Post -ContentType "application/json" -Body '{"question": "How much is a full day?"}'
   ```
   The boxes light up green and you get an answer back. The first answer can take 10 to 20
   seconds while the AI model loads.
7. **Switch it on for good.** Click **Publish** (you can name the version). The permanent address
   then works all the time, without the Execute button:
   ```
   Invoke-RestMethod -Uri http://127.0.0.1:5678/webhook/ask-docs -Method Post -ContentType "application/json" -Body '{"question": "What time do you open on Sundays?"}'
   ```

## Add documents from a web form

The second workflow, `add-documents.json`, gives you a small web page for adding documents. You
pick a file, n8n checks it and saves it into the project's `docs` folder, and the chat server's
folder watcher indexes it within about 10 seconds. No password or token is involved.

```
 you open the form ──► Upload form ──► Check the file ──► Save into docs ──► "Saved" page
                                            │
                                            └── wrong type, empty or too big ──► "Not saved" page
```

What the **Check the file** box allows: `.pdf`, `.docx`, `.txt` and `.md` files up to 10 MB. It
keeps only the file name (so a name like `..\..\x.md` cannot write outside `docs`), replaces odd
characters such as `:` or `?` with `_`, and refuses Word's `~$` lock files and empty files. **If a
file with the same name is already in `docs`, it is replaced**, which is also how you update a
document. n8n keeps no copy of the file.

1. **Restart n8n with the current start script.** The script now tells n8n that its file nodes may
   only write inside this project's `docs` folder (n8n otherwise blocks writing there). Stop n8n with
   Ctrl+C and start it again with `.\n8n\start-n8n.ps1`. If you ever start n8n any other way, saving
   fails with "Access to the file is not allowed".
2. **Import the workflow.** Create a new workflow, open **⋯** → **Import from File…** and pick
   `n8n\add-documents.json`.
3. **Check the folder.** Double-click **Check the file**. Its first line sets `DOCS_FOLDER` to
   `C:\Users\nbhas\rag-project\docs`. If your project lives somewhere else, change that path to your
   project's `docs` folder.
4. **Test it.** Click **Execute workflow**; a form opens in a new browser tab. Choose a small file,
   send it, and watch the boxes light up.
5. **Switch it on for good.** Click **Publish**. The form then lives permanently at
   `http://127.0.0.1:5678/form/add-document`.
6. **Check it worked.** The chat server's window should print a line like
   `[index] updated notes.md: 2 chunks`, and a question about the file's contents gets answered.

You can bookmark the form address. Uploading several files means filling the form once per file.

## Good to know

- **Two kinds of webhook address.** `/webhook-test/...` works once, only while the editor is
  listening after you click Execute, and lets you watch the data flow. `/webhook/...` is the
  permanent address and only works once the workflow is published.
- **Use `127.0.0.1`, not `localhost`.** On Windows, `localhost` can pause for a couple of seconds
  while PowerShell tries the IPv6 address first.
- **Click a box** on the canvas, or open the **Executions** tab, to see the exact data that went in
  and out of each step. It is the best way to debug a workflow.
- **Where n8n keeps its data:** `C:\Users\<you>\.n8n` (workflows, credentials, run history). Back
  that folder up if the workflows matter to you.
- **Stopping:** press Ctrl+C in the window where n8n or the chat server is running.
- **Do not commit a raw n8n export.** Exports include the owner's name and email address. To save
  a changed workflow here, export it, keep only its `name`, `nodes`, `connections` and `settings`,
  and check there is no personal detail in it.
- **n8n and Node versions.** n8n requires a recent Node.js (24 at the time of writing). Its own
  documentation says running it through `npm` is for local use and is being phased out in favour
  of its Docker image from n8n 3.0, so Docker is the long-term route if you depend on it.

## If something goes wrong

| What you see | Likely cause |
|---|---|
| `The requested webhook "ask-docs" is not registered` | You used the test address without clicking **Execute** first, or the permanent address before **Publish** |
| The HTTP Request box fails with 401 | The credential's value is not the token the chat server was started with (or the chat server was started without one set) |
| The HTTP Request box fails to connect | The chat server is not running, or n8n is calling `localhost` instead of `127.0.0.1` |
| `Port 8000 is already in use` | An older chat server is still running; stop it with Ctrl+C |
| The form says **Not saved** | Read its message: the file type is not supported, the file is empty, or it is over 10 MB |
| The **Save into docs** box fails with `Access to the file is not allowed` | n8n was not started with `.\n8n\start-n8n.ps1`, or `DOCS_FOLDER` in the **Check the file** box is not this project's `docs` folder |
| After sending, the result page stays blank for several seconds | Reload the page. n8n sometimes shows the result page before it is ready; the file was already handled |
| The form address shows `not registered` | The workflow is not published yet (use **Execute workflow** to try it first) |
| The file is saved but the chat does not know it | The chat server is not running, or was started with `RAG_WATCH=0`; run `python rag.py sync` |
