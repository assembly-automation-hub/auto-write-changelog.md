import os
import json
import time
from openai import OpenAI
from github import Github, Auth

gh_token = os.environ.get("GITHUB_TOKEN")
openai_api_key = os.environ.get("OPENAI_API_KEY")
repo_name = os.environ.get("REPOSITORY")
current_tag = os.environ.get("CURRENT_TAG")

MODEL_NAME = "gpt-4o"
client = OpenAI(api_key=openai_api_key)

auth = Auth.Token(gh_token)
gh = Github(auth=auth)
repo = gh.get_repo(repo_name)

# 1. Получаем список релизов
releases = list(repo.get_releases())
if len(releases) < 2:
    print("Not enough releases to compare. Exiting.")
    exit(0)

previous_tag = releases[1].tag_name
print(f"Comparing releases: {previous_tag} -> {current_tag}")

# 2. Получаем diff
comparison = repo.compare(previous_tag, current_tag)
diff_text = ""
exclude_extensions = ('.lock', '-lock.json', '.svg', '.png', '.jpg', '.min.js')

for file in comparison.files:
    if file.filename.endswith(exclude_extensions):
        continue
    if not file.patch:
        continue
        
    diff_text += f"File: {file.filename}\nPatch:\n{file.patch}\n\n"
    if len(diff_text) > 80000:
        diff_text += "\n[Diff truncated...]"
        break

if len(diff_text.strip()) < 50:
    print("Diff too small or empty. Skipping.")
    exit(0)

# 3. Инструкции для промпта (Адаптировано под 2 языка)
base_instructions = """
Return only a raw JSON object with no markdown formatting. The JSON must have these exact keys:
"en_improvements": list of strings (describe key improvements, new features, changed logic, or fixes in English),
"ru_improvements": list of strings (provide the exact Russian translation of the 'en_improvements' list)

Write clearly, concisely, and focus on the BUSINESS and LOGIC impact of the code changes.
"""

prompt = f"""Act as an Expert Software Engineer and Technical Translator.
Analyze the following code changes between version {previous_tag} and {current_tag}.
Translate these raw code changes into human-readable release notes for end users.

Changes:
{diff_text}

{base_instructions}"""

# 4. Вызов модели
def call_model(prompt: str, retries: int = 3, delay: int = 5) -> dict:
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                temperature=0.1,
                response_format={ "type": "json_object" }, 
                messages=[
                    {"role": "system", "content": "You are a professional technical writer and translator. Always return valid JSON only."},
                    {"role": "user", "content": prompt}
                ]
            )
            raw = response.choices[0].message.content.strip()
            return json.loads(raw)
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(delay)

    print("All attempts failed. Exiting gracefully.")
    exit(1)

result = call_model(prompt)

# 5. Формируем Markdown строго по шаблону
changelog_entry = f"## EN: Release Notes — Version {current_tag}\n"
changelog_entry += "### Key Improvements:**\n"

if result.get("en_improvements"):
    for item in result["en_improvements"]:
        changelog_entry += f"- {item}\n"
else:
    changelog_entry += "- No significant changes.\n"

changelog_entry += "\n---\n\n"

changelog_entry += f"## RU: Release Notes — Версия {current_tag}\n"
changelog_entry += "### Основные улучшения:**\n"

if result.get("ru_improvements"):
    for item in result["ru_improvements"]:
        changelog_entry += f"- {item}\n"
else:
    changelog_entry += "- Нет значительных изменений.\n"

changelog_entry += "\n\n"

# 6. Обновляем файл локально
filename = "Changelog.md"
existing_content = ""

if os.path.exists(filename):
    with open(filename, "r", encoding="utf-8") as file:
        existing_content = file.read()

with open(filename, "w", encoding="utf-8") as file:
    file.write(changelog_entry + existing_content)

print("Changelog file updated locally with bilingual format.")
