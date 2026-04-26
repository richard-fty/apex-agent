# Coding

Use this skill for frontend coding tasks where the goal is to edit a Vite React app, keep a concise checklist, and leave the app in a buildable state.

Workflow:
1. Inspect the relevant files before editing.
2. Create or update TodoItems for the task.
3. Make focused edits.
4. Run the relevant build or test command when available.
5. Call `start_app_preview` after the app builds or when the user asks to see it.
6. Surface patches and previews as artifacts.

Rules:
- Use the minimum stack already present in the template.
- Keep TodoItem statuses to `pending`, `in_progress`, `completed`, or `failed`.
- Do not add Next.js, a backend, or new infrastructure unless the task explicitly requires it.
- For frontend apps, the final user-visible deliverable should include an `app_preview` artifact unless the preview command fails.
