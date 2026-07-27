import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import apexCreative from "../extensions/apex-creative.ts";

interface RegisteredTool {
  name: string;
  execute: (...args: unknown[]) => Promise<{
    content: Array<{ type: string; text: string }>;
    details: Record<string, unknown>;
  }>;
}

function loadTools(): RegisteredTool[] {
  const tools: RegisteredTool[] = [];
  const fakeApi = {
    on: () => undefined,
    registerTool: (tool: unknown) => tools.push(tool as RegisteredTool),
  } as unknown as ExtensionAPI;
  apexCreative(fakeApi);
  return tools;
}

function toolNamed(tools: RegisteredTool[], name: string): RegisteredTool {
  const tool = tools.find((candidate) => candidate.name === name);
  assert.ok(tool, `missing tool ${name}`);
  return tool;
}

test("registers the Apex creative tool set", () => {
  const names = loadTools().map((tool) => tool.name);
  assert.deepEqual(names, [
    "apex_create_project",
    "apex_generate_music",
    "apex_analyze_music",
    "apex_generate_image",
    "apex_generate_video",
    "apex_render_mv",
  ]);
});

test("creates a project and a dry-run image job without provider calls", async () => {
  const cwd = await mkdtemp(join(tmpdir(), "apex-creative-test-"));
  const tools = loadTools();
  try {
    const createResult = await toolNamed(tools, "apex_create_project").execute(
      "call-create",
      {
        title: "Star Train",
        concept: "A girl chases a train made of stars.",
        durationSeconds: 30,
        aspectRatio: "16:9",
      },
      new AbortController().signal,
      undefined,
      { cwd },
    );
    assert.match(createResult.content[0]?.text || "", /Created Apex project star-train/);

    const projectPath = join(cwd, ".apex", "projects", "star-train", "project.json");
    const project = JSON.parse(await readFile(projectPath, "utf8")) as Record<string, unknown>;
    assert.equal(project.stage, "music_brief");
    assert.equal(project.format, "non_dialogue_animation_music_video");
    assert.deepEqual(project.dialogue, { enabled: false, lip_sync: false });

    const musicMapPath = join(cwd, ".apex", "projects", "star-train", "music-map.json");
    const musicMap = JSON.parse(await readFile(musicMapPath, "utf8")) as Record<
      string,
      unknown
    >;
    assert.equal(musicMap.status, "pending");
    assert.deepEqual(musicMap.beats, []);

    const imageResult = await toolNamed(tools, "apex_generate_image").execute(
      "call-image",
      {
        projectId: "star-train",
        shotId: "s010",
        prompt: "Anime heroine running beside a luminous celestial train",
        aspectRatio: "16:9",
      },
      new AbortController().signal,
      undefined,
      { cwd },
    );
    assert.match(imageResult.content[0]?.text || "", /No paid generation request was made/);
    const details = imageResult.details;
    const job = details.job as Record<string, unknown>;
    assert.equal(job.status, "planned");
    assert.equal(job.provider, "mock");
    assert.deepEqual(job.outputs, []);
  } finally {
    await rm(cwd, { recursive: true, force: true });
  }
});

test("plans music style switching, analysis, and a beat-timed non-dialogue shot", async () => {
  const cwd = await mkdtemp(join(tmpdir(), "apex-amv-test-"));
  const tools = loadTools();
  try {
    const musicResult = await toolNamed(tools, "apex_generate_music").execute(
      "call-music",
      {
        projectId: "neon-memory",
        prompt: "Change the arrangement to melancholic city pop",
        durationSeconds: 45,
        mode: "style_switch",
        sourceAudioPath: "/workspace/reference.wav",
        compositionId: "song-main",
        arrangementVersion: 2,
      },
      new AbortController().signal,
      undefined,
      { cwd },
    );
    const musicJob = musicResult.details.job as Record<string, unknown>;
    assert.deepEqual(musicJob.source_assets, ["/workspace/reference.wav"]);
    assert.equal(
      (musicJob.provider_params as Record<string, unknown>).preserve_composition,
      true,
    );

    const analysisResult = await toolNamed(tools, "apex_analyze_music").execute(
      "call-analysis",
      {
        projectId: "neon-memory",
        sourceAudioPath: "/workspace/selected.wav",
        durationSeconds: 45,
      },
      new AbortController().signal,
      undefined,
      { cwd },
    );
    const analysisJob = analysisResult.details.job as Record<string, unknown>;
    assert.equal(analysisJob.kind, "music_analysis");
    assert.equal(analysisJob.provider, "modal-sandbox");

    const videoResult = await toolNamed(tools, "apex_generate_video").execute(
      "call-video",
      {
        projectId: "neon-memory",
        shotId: "s030",
        prompt: "A woman turns under neon rain",
        motionPrompt: "slow camera push-in",
        durationSeconds: 4,
        musicSection: "chorus_1",
        beatRange: [48, 55],
        firstFramePath: "/workspace/s030-first.png",
        lastFramePath: "/workspace/s030-last.png",
        environmentMotion: ["rain", "neon reflections", "wind in hair"],
      },
      new AbortController().signal,
      undefined,
      { cwd },
    );
    const videoJob = videoResult.details.job as Record<string, unknown>;
    const providerParams = videoJob.provider_params as Record<string, unknown>;
    assert.equal(providerParams.generation_strategy, "first_last_frame");
    assert.deepEqual(providerParams.beat_range, [48, 55]);
    assert.equal(providerParams.dialogue, false);
    assert.equal(providerParams.lip_sync, false);
  } finally {
    await rm(cwd, { recursive: true, force: true });
  }
});
