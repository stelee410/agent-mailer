Read the `AGENT.md` file in the current working directory to get your identity:
- **Agent ID** (the UUID)
- **Address** (e.g. `coder@local`)
- **Broker URL** (e.g. `http://localhost:9800`)

You are forwarding a message to another agent. The user may provide:
- A message ID to forward
- A target agent name or address

**Steps:**

1. If the user didn't specify which message to forward, call the inbox API first:
   ```
   GET {broker_url}/messages/inbox/{address}?agent_id={agent_id}
   ```
   List the messages and ask which one to forward.

2. If the user didn't specify a target agent, list available agents:
   ```
   GET {broker_url}/agents
   ```
   Show the agent list (name, address, role) and ask who to forward to.

3. Fetch the thread for context:
   ```
   GET {broker_url}/messages/thread/{thread_id}
   ```

4. Mark the original message as read:
   ```
   PATCH {broker_url}/messages/{message_id}/read
   ```

5. Forward the message. Prefer **`forward_scope`** so the server builds quoted content (consistent formatting; thread view excludes per-message trash).

   - **`forward_scope`: `"message"`** — Recipient sees your optional `body` note, then **only the parent message** (the one identified by `parent_id`).
   - **`forward_scope`: `"thread"`** — Recipient sees your note, then **all messages in the thread** in order (chronological), separated by `---`. Omits messages in per-message trash.
   - **Omit `forward_scope`** — Legacy: `body` is stored exactly as you send it (you must paste quoted text yourself if needed).

   ```
   POST {broker_url}/messages/send
   {
     "agent_id": "{your_agent_id}",
     "from_agent": "{your_address}",
     "to_agent": "{target_agent_address}",
     "action": "forward",
     "subject": "Fwd: {original_subject}",
     "body": "{optional_note_to_recipient}",
     "parent_id": "{message_id_being_forwarded}",
     "forward_scope": "message"
   }
   ```
   Use `"forward_scope": "thread"` when the new agent needs full conversation context.

6. Confirm the forward was sent, showing the new message ID and thread ID.

$ARGUMENTS
