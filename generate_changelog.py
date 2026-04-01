import os
import json
import time
from openai import OpenAI
from github import Github, Auth

# ── Env vars ────────────────────────────────────────────────────────────────
gh_token       = os.environ.get("GH_PAT")
openai_api_key = os.environ.get("OPENAI_API_KEY")
repo_name      = os.environ.get("REPOSITORY")
current_tag    = os.environ.get("CURRENT_TAG")

if not gh_token:
    print("FATAL: GH_PAT not set"); exit(1)
if not openai_api_key:
    print("FATAL: OPENAI_API_KEY not set"); exit(1)
if not repo_name or not current_tag:
    print("FATAL: REPOSITORY or CURRENT_TAG not set"); exit(1)

# ── Clients ──────────────────────────────────────────────────────────────────
client = OpenAI(api_key=openai_api_key)
repo   = Github(auth=Auth.Token(gh_token)).get_repo(repo_name)

# ── Find previous release tag ────────────────────────────────────────────────
releases = list(repo.get_releases())
if len(releases) < 2:
    print("Need at least 2 releases to compare. Exiting."); exit(0)

previous_tag = releases[1].tag_name
print(f"Comparing: {previous_tag} → {current_tag}")

# ── Build diff text ───────────────────────────────────────────────────────────
EXCLUDE = ('.lock', '-lock.json', '.svg', '.png', '.jpg', '.jpeg', '.min.js', '.gif', '.ico')
comparison = repo.compare(previous_tag, current_tag)
diff_text = ""

for f in comparison.files:
    if f.filename.endswith(EXCLUDE) or not f.patch:
        continue
    diff_text += f"File: {f.filename}\nPatch:\n{f.patch}\n\n"
    if len(diff_text) > 80_000:
        diff_text += "\n[Diff truncated...]"
        break

if len(diff_text.strip()) < 50:
    print("Diff is too small or empty. Skipping."); exit(0)

# ── Call OpenAI ───────────────────────────────────────────────────────────────
PROMPT = f"""You are an expert software engineer and technical translator.
Analyze the code diff below (changes between version {previous_tag} and {current_tag}).
Return ONLY a raw JSON object — no markdown, no backticks.

Required keys:
  "en_improvements": list of strings — key improvements, new features, fixes (in English)
  "ru_improvements": list of strings — exact Russian translation of en_improvements

Focus on BUSINESS and USER-FACING impact. Be concise and clear.

Diff:
{diff_text}"""

def call_model(prompt: str, retries: int = 3, delay: int = 5) -> dict:
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are a professional technical writer. Return valid JSON only."},
                    {"role": "user",   "content": prompt}
                ]
            )
            return json.loads(response.choices[0].message.content.strip())
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    print("All attempts failed."); exit(1)

result = call_model(PROMPT)

# ── Build Markdown entry ──────────────────────────────────────────────────────
en_items = result.get("en_improvements") or []
ru_items = result.get("ru_improvements") or []

entry  = f"## EN: Release Notes — Version {current_tag}\n"
entry += "### Key Improvements:\n"
entry += "\n".join(f"- {i}" for i in en_items) if en_items else "- No significant changes."
entry += "\n\n---\n\n"
entry += f"## RU: Release Notes — Версия {current_tag}\n"
entry += "### Основные улучшения:\n"
entry += "\n".join(f"- {i}" for i in ru_items) if ru_items else "- Нет значительных изменений."
entry += "\n\n---\n\n"

# ── Write Changelog.md ────────────────────────────────────────────────────────
filename = "Changelog.md"
existing = open(filename, encoding="utf-8").read() if os.path.exists(filename) else ""

# Skip if this version is already documented
if f"Version {current_tag}" in existing or f"Версия {current_tag}" in existing:
    print(f"Entry for {current_tag} already exists. Skipping."); exit(0)

with open(filename, "w", encoding="utf-8") as fh:
    fh.write(entry + existing)

print(f"Changelog.md updated for {current_tag}.")
