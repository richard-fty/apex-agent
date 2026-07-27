import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

type JobKind = "image" | "video" | "music" | "music_analysis" | "render";

interface PlannedJob {
  job_id: string;
  project_id: string;
  kind: JobKind;
  status: "planned";
  provider: string;
  model: null;
  prompt: string;
  negative_prompt: string | null;
  source_assets: string[];
  provider_params: Record<string, unknown>;
  estimated_cost_usd: null;
  actual_cost_usd: null;
  seed: number | null;
  outputs: string[];
  created_at: string;
}

function safeId(value: string): string {
  const normalized = value
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return normalized || `project-${randomUUID().slice(0, 8)}`;
}

async function saveJson(path: string, value: unknown): Promise<void> {
  await mkdir(join(path, ".."), { recursive: true });
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function planJob(
  cwd: string,
  input: {
    projectId: string;
    kind: JobKind;
    prompt: string;
    negativePrompt?: string;
    sourceAssets?: string[];
    provider?: string;
    seed?: number;
    providerParams?: Record<string, unknown>;
  },
): Promise<{ job: PlannedJob; path: string }> {
  const jobId = `job_${Date.now()}_${randomUUID().slice(0, 8)}`;
  const job: PlannedJob = {
    job_id: jobId,
    project_id: safeId(input.projectId),
    kind: input.kind,
    status: "planned",
    provider: input.provider || process.env[`APEX_${input.kind.toUpperCase()}_PROVIDER`] || "mock",
    model: null,
    prompt: input.prompt,
    negative_prompt: input.negativePrompt || null,
    source_assets: input.sourceAssets || [],
    provider_params: input.providerParams || {},
    estimated_cost_usd: null,
    actual_cost_usd: null,
    seed: input.seed ?? null,
    outputs: [],
    created_at: new Date().toISOString(),
  };
  const path = join(cwd, ".apex", "projects", job.project_id, "jobs", `${jobId}.json`);
  await saveJson(path, job);
  return { job, path };
}

function plannedResult(job: PlannedJob, path: string) {
  return {
    content: [
      {
        type: "text" as const,
        text:
          `Planned ${job.kind} job ${job.job_id} with provider ${job.provider}. ` +
          `No paid generation request was made. Job manifest: ${path}`,
      },
    ],
    details: { job, manifestPath: path },
  };
}

function detectSkillRoutes(text: string): Array<{
  name: string;
  status: "matched" | "activated";
  reason: string;
}> {
  const explicit = text.match(/^\/skill:([a-z0-9-]+)/i);
  if (explicit) {
    return [
      {
        name: explicit[1].toLowerCase(),
        status: "activated",
        reason: "Explicit /skill command",
      },
    ];
  }

  const creativeSignals = [
    /动漫|动画|二次元|分镜|镜头|生图|图像|视频|音乐|角色|风格|创作/i,
    /\banime\b|\bmv\b|music video|storyboard|shot list|image generation|video generation|music generation/i,
  ];
  const matchedSignal = creativeSignals.find((pattern) => pattern.test(text));
  if (!matchedSignal) return [];
  return [
    {
      name: "apex-anime-mv",
      status: "matched",
      reason: `Apex creative router matched ${matchedSignal}`,
    },
  ];
}

export default function apexCreative(pi: ExtensionAPI): void {
  pi.on("project_trust", (event) => {
    if (event.cwd === process.cwd()) {
      return { trusted: "yes", remember: false };
    }
    return { trusted: "undecided" };
  });

  pi.on("input", (event, ctx) => {
    ctx.ui.setStatus(
      "apex-skill-routing",
      JSON.stringify({
        source: event.source,
        skills: detectSkillRoutes(event.text),
      }),
    );
    return { action: "continue" };
  });

  pi.registerTool({
    name: "apex_create_project",
    label: "Create Apex Project",
    description:
      "Create the reproducible folder and project manifest for an anime MV or other generative production.",
    parameters: Type.Object({
      title: Type.String({ description: "Project title" }),
      concept: Type.String({ description: "Core story, emotion, or creative premise" }),
      durationSeconds: Type.Number({ minimum: 5, maximum: 900 }),
      aspectRatio: Type.Optional(Type.String({ description: "For example 16:9, 9:16, or 1:1" })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const projectId = safeId(params.title);
      const root = join(ctx.cwd, ".apex", "projects", projectId);
      for (const dir of [
        "jobs",
        "assets/references",
        "assets/images",
        "assets/video",
        "assets/audio",
        "assets/storyboards",
        "previews",
        "renders",
      ]) {
        await mkdir(join(root, dir), { recursive: true });
      }
      const project = {
        schema_version: 1,
        project_id: projectId,
        title: params.title,
        concept: params.concept,
        format: "non_dialogue_animation_music_video",
        workflow_mode: "music_first",
        dialogue: {
          enabled: false,
          lip_sync: false,
        },
        duration_seconds: params.durationSeconds,
        aspect_ratio: params.aspectRatio || "16:9",
        stage: "music_brief",
        created_at: new Date().toISOString(),
      };
      const manifestPath = join(root, "project.json");
      await saveJson(manifestPath, project);
      await Promise.all([
        saveJson(join(root, "music-spec.json"), {
          schema_version: 1,
          status: "unlocked",
          source_asset: null,
          generation_mode: null,
          composition_id: null,
          arrangement_version: 0,
          rights: null,
        }),
        saveJson(join(root, "music-map.json"), {
          schema_version: 1,
          status: "pending",
          bpm: null,
          beats: [],
          sections: [],
          energy_curve: [],
          lyric_cues: [],
          cut_points: [],
        }),
        saveJson(join(root, "visual-treatment.json"), {
          schema_version: 1,
          status: "draft",
          narrative_mode: "visual_only",
          dialogue_mode: "none",
          emotional_arc: [],
          visual_motifs: [],
        }),
        saveJson(join(root, "characters.json"), {
          schema_version: 1,
          characters: [],
        }),
        saveJson(join(root, "locations.json"), {
          schema_version: 1,
          locations: [],
        }),
        saveJson(join(root, "storyboard.json"), {
          schema_version: 1,
          status: "draft",
          panels: [],
        }),
        saveJson(join(root, "shots.json"), {
          schema_version: 1,
          status: "draft",
          shots: [],
        }),
        saveJson(join(root, "timeline.json"), {
          schema_version: 1,
          status: "draft",
          audio: [],
          video: [],
          ambience: [],
          effects: [],
        }),
      ]);
      return {
        content: [
          {
            type: "text",
            text: `Created Apex project ${projectId}. Manifest: ${manifestPath}`,
          },
        ],
        details: { project, manifestPath },
      };
    },
  });

  pi.registerTool({
    name: "apex_generate_music",
    label: "Plan Music Generation or Style Switch",
    description:
      "Create a provider-neutral original-music or music-style-switch job without making a paid request.",
    parameters: Type.Object({
      projectId: Type.String(),
      prompt: Type.String(),
      durationSeconds: Type.Number({ minimum: 5, maximum: 900 }),
      mode: Type.Optional(
        Type.Union([Type.Literal("original"), Type.Literal("style_switch")]),
      ),
      sourceAudioPath: Type.Optional(Type.String()),
      compositionId: Type.Optional(Type.String()),
      arrangementVersion: Type.Optional(Type.Integer({ minimum: 1 })),
      preserveComposition: Type.Optional(Type.Boolean()),
      instrumental: Type.Optional(Type.Boolean()),
      lyrics: Type.Optional(Type.String()),
      provider: Type.Optional(Type.String()),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const mode = params.mode || (params.sourceAudioPath ? "style_switch" : "original");
      if (mode === "style_switch" && !params.sourceAudioPath) {
        throw new Error("sourceAudioPath is required for music style switching");
      }
      const { job, path } = await planJob(ctx.cwd, {
        projectId: params.projectId,
        kind: "music",
        prompt: params.prompt,
        sourceAssets: params.sourceAudioPath ? [params.sourceAudioPath] : [],
        provider: params.provider,
        providerParams: {
          mode,
          duration_seconds: params.durationSeconds,
          composition_id: params.compositionId || null,
          arrangement_version: params.arrangementVersion || 1,
          preserve_composition: params.preserveComposition ?? mode === "style_switch",
          instrumental: params.instrumental ?? !params.lyrics,
          lyrics: params.lyrics || null,
        },
      });
      return plannedResult(job, path);
    },
  });

  pi.registerTool({
    name: "apex_analyze_music",
    label: "Plan Music Analysis",
    description:
      "Plan deterministic analysis of a selected track into beats, sections, energy, lyric cues, and edit points.",
    parameters: Type.Object({
      projectId: Type.String(),
      sourceAudioPath: Type.String(),
      durationSeconds: Type.Optional(Type.Number({ minimum: 5, maximum: 900 })),
      knownBpm: Type.Optional(Type.Number({ minimum: 20, maximum: 300 })),
      provider: Type.Optional(Type.String()),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const { job, path } = await planJob(ctx.cwd, {
        projectId: params.projectId,
        kind: "music_analysis",
        prompt: "Analyze the selected track for a non-dialogue animation music video",
        sourceAssets: [params.sourceAudioPath],
        provider: params.provider || "modal-sandbox",
        providerParams: {
          duration_seconds: params.durationSeconds || null,
          known_bpm: params.knownBpm || null,
          features: [
            "bpm",
            "beats",
            "sections",
            "energy_curve",
            "lyric_cues",
            "cut_points",
          ],
          output: "music-map.json",
        },
      });
      return plannedResult(job, path);
    },
  });

  pi.registerTool({
    name: "apex_generate_image",
    label: "Plan Image Generation",
    description:
      "Create a provider-neutral character, location, storyboard, or keyframe image job. The default mock provider only writes a reproducible manifest.",
    parameters: Type.Object({
      projectId: Type.String(),
      shotId: Type.String(),
      prompt: Type.String(),
      negativePrompt: Type.Optional(Type.String()),
      referencePaths: Type.Optional(Type.Array(Type.String())),
      aspectRatio: Type.Optional(Type.String()),
      provider: Type.Optional(Type.String()),
      seed: Type.Optional(Type.Integer()),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const { job, path } = await planJob(ctx.cwd, {
        projectId: params.projectId,
        kind: "image",
        prompt: params.prompt,
        negativePrompt: params.negativePrompt,
        sourceAssets: params.referencePaths,
        provider: params.provider,
        seed: params.seed,
        providerParams: {
          shot_id: params.shotId,
          aspect_ratio: params.aspectRatio || "16:9",
          dialogue: false,
          lip_sync: false,
        },
      });
      return plannedResult(job, path);
    },
  });

  pi.registerTool({
    name: "apex_generate_video",
    label: "Plan Beat-Timed Animation Shot",
    description:
      "Create a provider-neutral non-dialogue animation shot job, preferably from a first frame or first/last frames.",
    parameters: Type.Object({
      projectId: Type.String(),
      shotId: Type.String(),
      prompt: Type.String(),
      motionPrompt: Type.Optional(Type.String()),
      negativePrompt: Type.Optional(Type.String()),
      durationSeconds: Type.Number({ minimum: 1, maximum: 30 }),
      musicSection: Type.Optional(Type.String()),
      beatRange: Type.Optional(
        Type.Tuple([
          Type.Integer({ minimum: 0 }),
          Type.Integer({ minimum: 0 }),
        ]),
      ),
      characterAction: Type.Optional(Type.String()),
      environmentMotion: Type.Optional(Type.Array(Type.String())),
      sourceImagePath: Type.Optional(Type.String()),
      firstFramePath: Type.Optional(Type.String()),
      lastFramePath: Type.Optional(Type.String()),
      provider: Type.Optional(Type.String()),
      seed: Type.Optional(Type.Integer()),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const firstFramePath = params.firstFramePath || params.sourceImagePath;
      const sourceAssets = [firstFramePath, params.lastFramePath].filter(
        (value): value is string => typeof value === "string" && value.length > 0,
      );
      const generationStrategy = params.lastFramePath
        ? "first_last_frame"
        : firstFramePath
          ? "image_to_video"
          : "text_to_video";
      const { job, path } = await planJob(ctx.cwd, {
        projectId: params.projectId,
        kind: "video",
        prompt: params.prompt,
        negativePrompt: params.negativePrompt,
        sourceAssets,
        provider: params.provider,
        seed: params.seed,
        providerParams: {
          shot_id: params.shotId,
          duration_seconds: params.durationSeconds,
          music_section: params.musicSection || null,
          beat_range: params.beatRange || null,
          character_action: params.characterAction || null,
          environment_motion: params.environmentMotion || [],
          motion_prompt: params.motionPrompt || null,
          generation_strategy: generationStrategy,
          dialogue: false,
          lip_sync: false,
        },
      });
      return plannedResult(job, path);
    },
  });

  pi.registerTool({
    name: "apex_render_mv",
    label: "Plan MV Render",
    description:
      "Create a final composition/render job from an approved timeline. The mock provider does not render media.",
    parameters: Type.Object({
      projectId: Type.String(),
      timelinePath: Type.String(),
      resolution: Type.Optional(Type.String()),
      fps: Type.Optional(Type.Number({ minimum: 12, maximum: 120 })),
      provider: Type.Optional(Type.String()),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const { job, path } = await planJob(ctx.cwd, {
        projectId: params.projectId,
        kind: "render",
        prompt: `Render approved timeline ${params.timelinePath}`,
        sourceAssets: [params.timelinePath],
        provider: params.provider,
        providerParams: {
          resolution: params.resolution || "1920x1080",
          fps: params.fps || 24,
          dialogue: false,
          lip_sync: false,
        },
      });
      return plannedResult(job, path);
    },
  });
}
