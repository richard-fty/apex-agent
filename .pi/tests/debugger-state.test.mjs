import assert from "node:assert/strict";
import test from "node:test";
import {
  DebuggerStore,
  mediaForOutput,
  summarizeRun,
} from "../bridge/public/debugger-state.js";

function bridge(kind, value, sequence) {
  return {
    kind,
    ...value,
    bridge_seq: sequence,
    bridge_timestamp: `2026-07-24T08:00:0${sequence}.000Z`,
  };
}

function pi(event, sequence) {
  return bridge("pi_event", { event }, sequence);
}

test("builds a skill, thinking, tool, response, and artifact execution chain", () => {
  const store = new DebuggerStore();
  store.ingest(
    bridge(
      "bridge_command",
      {
        command: {
          id: "prompt-1",
          type: "prompt",
          message: "Create an anime MV image look test",
        },
      },
      1,
    ),
  );
  store.ingest(pi({ type: "agent_start" }, 2));
  store.ingest(pi({ type: "turn_start" }, 3));
  store.ingest(
    pi(
      {
        type: "extension_ui_request",
        method: "setStatus",
        statusKey: "apex-skill-routing",
        statusText: JSON.stringify({
          skills: [
            {
              name: "apex-anime-mv",
              status: "matched",
              reason: "router fixture",
            },
          ],
        }),
      },
      4,
    ),
  );
  store.ingest(
    pi(
      {
        type: "message_update",
        assistantMessageEvent: {
          type: "thinking_delta",
          contentIndex: 0,
          delta: "I should establish a visual bible first.",
        },
      },
      5,
    ),
  );
  store.ingest(
    pi(
      {
        type: "tool_execution_start",
        toolCallId: "call-image",
        toolName: "apex_generate_image",
        args: { projectId: "stars", prompt: "cel animation train" },
      },
      6,
    ),
  );
  store.ingest(
    pi(
      {
        type: "tool_execution_end",
        toolCallId: "call-image",
        toolName: "apex_generate_image",
        isError: false,
        result: {
          content: [{ type: "text", text: "Planned image job" }],
          details: {
            manifestPath:
              "/Users/tianye-paw/Desktop/WorkSpace/apex-agent/.apex/projects/stars/jobs/job-1.json",
            job: {
              job_id: "job-1",
              kind: "image",
              status: "planned",
              provider: "mock",
              prompt: "cel animation train",
              outputs: [],
            },
          },
        },
      },
      7,
    ),
  );
  store.ingest(
    pi(
      {
        type: "message_update",
        assistantMessageEvent: {
          type: "text_end",
          contentIndex: 1,
          content: "The look-test job is planned.",
        },
      },
      8,
    ),
  );
  store.ingest(pi({ type: "agent_settled" }, 9));

  const run = store.runs[0];
  assert.equal(run.status, "complete");
  assert.equal(run.skills[0].name, "apex-anime-mv");
  assert.equal(run.skills[0].status, "activated");
  assert.match(run.skills[0].reason, /apex_generate_image/);
  assert.equal(run.nodes.find((node) => node.type === "thinking").content, "I should establish a visual bible first.");
  assert.equal(run.nodes.find((node) => node.type === "tool").status, "complete");
  assert.equal(run.nodes.find((node) => node.type === "response").content, "The look-test job is planned.");
  assert.equal(run.outputs[0].title, "job-1");
  assert.equal(summarizeRun(run).tools, 1);
});

test("replays bridge snapshots and discovers Pi skills", () => {
  const store = new DebuggerStore();
  store.ingest({
    kind: "bridge_snapshot",
    events: [
      bridge("bridge_status", { status: "running", pid: 1234 }, 1),
      pi(
        {
          type: "response",
          command: "get_commands",
          success: true,
          data: {
            commands: [
              {
                name: "skill:apex-anime-mv",
                source: "skill",
                description: "Anime MV production",
                location: "project",
                path: "/project/.pi/skills/apex-anime-mv/SKILL.md",
              },
            ],
          },
        },
        2,
      ),
    ],
  });

  assert.equal(store.runtime.bridgeStatus, "running");
  assert.equal(store.availableSkills[0].name, "apex-anime-mv");
  assert.equal(store.rawEvents.length, 2);
});

test("only turns local output paths into the guarded asset endpoint", () => {
  const media = mediaForOutput({
    paths: [
      "/Users/tianye-paw/Desktop/WorkSpace/apex-agent/.apex/projects/demo/output.png",
      "https://example.com/output.mp4",
    ],
  });
  assert.equal(media[0].type, "image");
  assert.match(media[0].source, /^\/asset\?path=/);
  assert.equal(media[1].type, "video");
  assert.equal(media[1].source, "https://example.com/output.mp4");
});
