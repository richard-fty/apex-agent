# Non-dialogue animation music video workflow contract

## Stage gates

| Stage | Required output | Advance when |
| --- | --- | --- |
| Brief | `creative-brief.json` | Intent, audience, duration, format, references, constraints are known |
| Music | `music-spec.json`, selected audio | Composition and arrangement version are selected and rights are recorded |
| Music analysis | `music-map.json` | Beats, sections, energy, lyric cues, and edit points cover the selected track |
| Visual treatment | `visual-treatment.json` | User selects a non-dialogue visual story and emotional arc |
| Design | `style-bible.md`, `characters.json`, `locations.json` | Hero character, palette, locations, and negative constraints are approved |
| Storyboard | `storyboard.json` | Every musical section has visual intent and beat-aligned timing |
| Shot planning | `shots.json` | Every shot has a stable ID, beat range, continuity links, action, and generation strategy |
| Look test | Representative images and clips | Identity, style, and motion pass review |
| Animatic | `timeline.json`, low-resolution preview | Visual story and musical rhythm are approved before paid video generation |
| Production | Versioned source assets | Required image and video shots exist |
| Assembly | `timeline.json`, preview render | Timing, transitions, mix, and captions pass review |
| Delivery | Final media and `render-report.json` | Export settings and provenance are recorded |

## Project layout

```text
.apex/projects/<project-id>/
├── project.json
├── creative-brief.json
├── music-spec.json
├── music-map.json
├── visual-treatment.json
├── style-bible.md
├── characters.json
├── locations.json
├── storyboard.json
├── shots.json
├── jobs/
├── assets/
│   ├── references/
│   ├── images/
│   ├── video/
│   └── audio/
├── timeline.json
└── renders/
```

## Generation job

Every provider adapter should return or persist these common fields:

```json
{
  "job_id": "job_<stable-id>",
  "project_id": "project-id",
  "kind": "image | video | music | music_analysis | render",
  "status": "planned | submitted | running | completed | failed",
  "provider": "mock",
  "model": null,
  "prompt": "...",
  "negative_prompt": null,
  "source_assets": [],
  "provider_params": {},
  "estimated_cost_usd": null,
  "actual_cost_usd": null,
  "seed": null,
  "outputs": [],
  "created_at": "ISO-8601"
}
```

`planned` means that no paid provider request has been made. Never present a
planned job as generated media.

## Shot record

Each shot should contain:

- `id`: stable identifier such as `s010`.
- `start_seconds` and `duration_seconds`.
- `music_section` and `beat_range`.
- `story_purpose` and `emotion`.
- `characters`, `location`, `props`, `character_action`, and `continuity_from`.
- `composition`, `camera`, `environment_motion`, `lighting`, and `palette`.
- `image_prompt`, `motion_prompt`, `negative_prompt`, and
  `generation_strategy`.
- `source_assets` and provider-specific parameters.
- `status`, review notes, selected output, and rejected outputs.

Dialogue and lip sync are disabled by default. Vocal lyrics can influence
emotion, cut points, and visual motifs, but are not assigned to a speaking
character.

## Review rubric

Score representative outputs from 1–5 for:

1. Character identity and costume consistency.
2. Composition and silhouette readability.
3. Background and prop continuity.
4. Motion quality and temporal stability.
5. Match to musical beat and narrative purpose.
6. Technical fitness: resolution, frame rate, duration, and artifacts.

Do not batch the remaining production when a critical dimension scores below 3.
