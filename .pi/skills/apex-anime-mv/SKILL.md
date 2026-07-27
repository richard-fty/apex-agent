---
name: apex-anime-mv
description: Plan and produce original non-dialogue, music-driven animation music videos through a reproducible creative workflow. Use for AMV concepts, music generation or style switching, visual treatments, character and style bibles, storyboards, beat-timed shot lists, image or video generation, timeline assembly, final rendering, or analyzing a reference workflow to create a new work with similar abstract production principles.
---

# Apex Animation Music Video

Build a coherent production rather than a collection of unrelated generations.
Record important creative and technical choices in project artifacts so shots can
be regenerated, reviewed, and assembled consistently.

The default format is a non-dialogue animation music video. Characters do not
speak and no lip-sync step is required. Songs may contain vocals; lyrics are
treated as timing and emotional cues rather than character dialogue.

## Choose the operating mode

- Use **ideate** when the user only has a theme, lyric, mood, or reference.
- Use **plan** when the user wants a treatment, style bible, storyboard, or shot list.
- Use **produce** when generation tools and provider credentials are available.
- Use **remix** when analyzing references. Extract pacing, composition, palette,
  transition, and sound-design principles; create original characters and assets.

## Run the workflow

1. Capture the creative brief: audience, emotion, duration, aspect ratio,
   platform, music source or generation status, references, budget, deadline,
   rights, and hard constraints. Infer low-risk details; ask only about decisions
   that change the creative direction or cost.
2. Generate, upload, or style-switch the music. Keep composition and arrangement
   versions separate. Do not lock final shot timing until a track is selected.
3. Analyze the selected track into a machine-readable music map containing BPM,
   beats, sections, energy, lyric cues when present, and candidate edit points.
4. Offer two or three visual treatments. State the narrative hook, emotional arc,
   recurring motifs, visual grammar, music relationship, production complexity,
   and principal risk of each. Do not write character dialogue.
5. Freeze a style bible, character bible, and location bible before batch
   generation. Define
   palette, line and shading language, costume, locations, lighting, lenses,
   camera motion, negative prompts, and consistency references.
6. Build a beat-timed storyboard and machine-readable shot manifest. Give every
   shot a stable ID and record its music section, beat range, duration, purpose,
   character action, environment motion, prompt, references, continuity,
   transition, provider settings, and status.
7. Generate a small representative set first: hero character, key location, and
   two shots with different motion demands. Ask for approval before the full batch
   or any paid generation.
8. Assemble the storyboard frames against the selected track as a low-resolution
   animatic. Approve its story readability and musical timing before video
   generation.
9. Generate and review assets. Prefer image-to-video or first/last-frame video
   over unconstrained text-to-video. Reject outputs with identity drift, broken anatomy,
   discontinuous props, unreadable silhouettes, unwanted text, or timing mismatch.
10. Assemble picture, music, ambience, and effects into a timeline.
   Render a low-resolution preview before the final export.
11. Deliver the final render together with the project manifest, sources, model
   settings, cost summary, known limitations, and regeneration instructions.

Read [references/workflow.md](references/workflow.md) when creating manifests,
mapping tool outputs, or deciding whether a stage is ready to advance.

## Use generation tools safely

- Prefer Apex-prefixed creative tools when available.
- Treat a `mock` or `planned` result as a job specification, not generated media.
- Do not expose provider credentials in prompts, logs, manifests, or shell output.
- Require explicit approval for a provider call that can incur material cost.
- Keep provider-specific data under `provider_params`; keep the core manifest
  provider-neutral.
- Preserve seeds and reference asset hashes when the provider exposes them.

## Maintain creative continuity

- Refer to characters, locations, props, costumes, and palette by stable IDs.
- Change the style bible explicitly; do not silently mutate it between shots.
- Separate content prompts from camera and motion instructions.
- Drive shot duration and transitions from the selected music map.
- Prefer simple expressive motion: walking, turning, looking, wind, rain,
  reflections, fabric, lighting, vehicles, and controlled camera movement.
- Avoid speech-like mouth motion unless the user explicitly changes the project
  away from the default non-dialogue format.
- Validate adjacent shots together, not only as isolated images.
- Keep the story readable without relying on generated on-screen text.

## Finish honestly

Call a production complete only when the requested artifact exists and has passed
the relevant review gate. Otherwise state the exact current stage and the next
action required.
