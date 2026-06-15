# K.I.N.E.T.I.C. — Use Cases

Practical examples for each feature. All examples assume you're talking to the agent via the Web UI chat or Telegram.

---

## 1. Chat & Sessions

### Basic chat
```
You: What's the weather in Tokyo?
Agent: Let me search that for you...
```

### Sessions — keep separate contexts
```
You: /session new work
Agent: ✓ Switched to session 'work'

You: /session list
Agent: Sessions:
  default
  work ← active

You: /session default
Agent: ✓ Switched to session 'default'
```

---

## 2. Long-Term Memory

No explicit command needed. The agent automatically:
- Archives compressed conversation summaries into the knowledge base
- Recalls relevant past memories before each response

**Example:**
```
Day 1 — You: I'm planning a trip to Japan next month.
Day 30 — You: What was I planning?
           Agent recalls the Japan trip from archived memory.
```

You can also explicitly save facts:
```
You: Remember that my favorite color is blue.
Agent: ✓ Saved.
```

---

## 3. File Upload

Upload a file through the Web UI chat (click the 📎 button).

### Text file
Upload `notes.txt`:
```
Agent: [Uploaded Text file: notes.txt (243 bytes)]

I've read your notes. Here's a summary...
```

### PDF
Upload `report.pdf`:
```
Agent: [Uploaded PDF document: report.pdf (3 pages)]

The report covers Q1 earnings...
```

### CSV
Upload `sales.csv`:
```
Agent: [Uploaded CSV spreadsheet: sales.csv (150 rows, columns: Date, Product, Amount)]

First 5 rows:
  {"Date": "2024-01-01", "Product": "Widget A", "Amount": "100"}
  ...
```

### With a message
Upload `budget.xlsx` + type "Summarize this":
```
Agent: [Uploaded Text file: budget.xlsx (12 KB)]
User message: Summarize this

Here's the budget summary...
```

---

## 4. Browser Automation

The agent can browse the web autonomously.

### Navigate and extract
```
You: Go to wikipedia and search for "quantum computing"
Agent navigates to wikipedia.org, types "quantum computing" in the search box,
clicks search, and extracts the summary paragraph.
```

### Check a website
```
You: What's the latest post on Hacker News?
Agent: I'll navigate there and extract the top stories.

Navigated to https://news.ycombinator.com
Top stories:
  1. Show HN: ...
  2. ...
```

### Multi-step interaction
```
You: Go to example.com/login, fill in the username "admin" and click submit
Agent navigates, fills the form, clicks submit.
```

---

## 5. Email

Requires `EMAIL_*` env vars in `.env`.

### Read recent emails
```
You: Check my inbox
Agent reads last 10 emails from INBOX.
```

### Send an email
```
You: Send an email to boss@company.com saying "Meeting confirmed for 3pm"
Agent sends the email.
```

### Check for specific emails
```
You: Any emails from Amazon today?
Agent reads recent emails and filters for Amazon.
```

---

## 6. Code Execution

Run Python code in a sandbox.

### Calculation
```
You: Calculate the compound interest on $10,000 at 5% for 3 years
Agent runs Python code and returns the result.
```

### Data analysis
```
You: Given this list of numbers [45, 67, 23, 89, 12, 56], find the mean, median, and standard deviation
Agent writes and runs Python code to compute statistics.
```

### Automation script
```
You: Write a script that generates a multiplication table for 1-5 and run it
Agent writes the code, executes it, returns the table.
```

---

## 7. Image Generation

Requires `"image"` section in `config/models.json`.

### Generate an image
```
You: Generate an image of a sunset over mountains with a lake
Agent: Generated 1 image(s):
  • https://...
```

### With specific size
```
You: Generate a wide banner image of a tech conference
Agent generates 1792x1024 image.
```

### Multiple variations
```
You: Generate 3 different logo concepts for a coffee shop called "Bean There"
Agent generates 3 variations.
```

---

## 8. Monitors (Proactive Agents)

Create background checks that notify you.

### Price monitor
```
You: Create a monitor that checks if Apple stock drops below $200, every 6 hours
Agent: ✓ Monitor created: "Apple stock check"
         Check prompt: Is Apple stock below $200?
         Interval: 360 minutes
         First check at: 2025-01-15T18:00:00
```

### Email monitor
```
You: Monitor my inbox for emails from "urgent@company.com" every 30 minutes
Agent: ✓ Monitor created.
```

### News monitor
```
You: Check if there's news about "AI regulation" every hour and alert me
Agent: ✓ Monitor created.
```

### List active monitors
```
You: List my monitors
Agent: Active monitors:
  • Stock check — next check: 2025-01-15T18:00:00
  • Email watch — next check: 2025-01-15T15:30:00
```

### Stop a monitor
```
You: /task remove task_1712345678000
Agent: ✓ Task removed.
```

---

## 9. Scheduled Tasks

### One-time reminder
```
You: Remind me to call mom in 30 minutes
Agent: ✓ Scheduled: "call mom" in 30m.
```

### Recurring reminder
```
You: Remind me to stand up and stretch every hour during work
Agent: ✓ Scheduled: "stand up and stretch" every 60m (recurring).
```

### List scheduled tasks
```
You: /task list
Agent: Scheduled tasks:
  • call mom (once) — next: 2:30 PM
  • stand up (every 60m) — next: 3:00 PM
```

---

## 10. Pipelines

Chain multiple agent calls.

### Multi-step processing
```
You: Create a pipeline that summarizes a webpage then translates to Spanish
Agent creates the pipeline with two steps:
  1. fetch_and_summarize → output: summary
  2. translate_to_spanish({{summary}}) → output: translation
```

### Execute a pipeline
```
You: Run my "summarize and translate" pipeline with url=https://example.com
Agent executes the pipeline and returns both the summary and translation.
```

---

## 11. Knowledge Base

Requires embedding config in models.json.

### Index a webpage
```
You: Save this URL to my knowledge base: https://en.wikipedia.org/wiki/Python
Agent fetches the page, chunks it, embeds it, and indexes it.
```

### Query knowledge
```
You: What do I have in my knowledge base about Python?
Agent searches the knowledge base and returns relevant chunks.
```

### List knowledge base stats
```
You: /knowledge
Agent: Knowledge base: 5 documents, 23 chunks.
```
