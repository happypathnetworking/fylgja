""".claude/hooks/command-log.py: the record keeps the command's own prompt and never a
follow-up's text, which is the operator's answer (docs/development.md, "Commands are
logged automatically"). Run: python3 -I -m unittest discover -s scripts/tests."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
HOOK = os.path.join(ROOT, ".claude", "hooks", "command-log.py")


def user(uuid, at, text):
    return {"type": "user", "uuid": uuid, "sessionId": "s1", "timestamp": at, "version": "2.1.301",
            "message": {"role": "user", "content": text}}


def assistant(uuid, at, text, req):
    return {"type": "assistant", "uuid": uuid, "sessionId": "s1", "timestamp": at, "requestId": req,
            "effort": "high",
            "message": {"role": "assistant", "model": "claude-fable-5-1", "stop_reason": "end_turn",
                        "usage": {"input_tokens": 10, "cache_creation_input_tokens": 100,
                                  "cache_read_input_tokens": 1000, "output_tokens": 50},
                        "content": [{"type": "text", "text": text}]}}


CLARIFY = ("<command-message>speckit-clarify</command-message>\n<command-name>/speckit-clarify</command-name>\n"
           "<command-args>the spec's open points</command-args>")


def replay(rows):
    out = tempfile.mkdtemp()
    t = os.path.join(out, "transcript.jsonl")
    with open(t, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=ROOT)
    subprocess.run([sys.executable, HOOK, "replay", t, "--out", out], check=True, env=env, capture_output=True)
    rec = json.loads(open(os.path.join(out, "commands", "runs.jsonl")).readline())
    log = open(os.path.join(out, "commands", "log.md")).read()
    return rec, log, out


ROWS = [
    user("u1", "2026-10-28T10:00:00Z", CLARIFY),
    assistant("a1", "2026-10-28T10:00:30Z", "Q1: which? A) this B) that", "r1"),
    user("u2", "2026-10-28T10:01:00Z", "A, and keep the name"),
    assistant("a2", "2026-10-28T10:01:20Z", "Recorded. Coverage: clear.", "r2"),
]


class FollowUpsAreNotRecorded(unittest.TestCase):
    def test_the_commands_own_prompt_is_kept(self):
        rec, log, _ = replay(ROWS)
        self.assertEqual(rec["segments"][0]["prompt"], "the spec's open points")
        self.assertIn("the spec's open points", log)

    def test_a_follow_ups_text_is_not_kept_but_its_metrics_are(self):
        rec, log, _ = replay(ROWS)
        self.assertEqual(len(rec["segments"]), 2)
        self.assertIsNone(rec["segments"][1]["prompt"])
        self.assertEqual(rec["follow_ups"]["segments"], 1)
        self.assertNotIn("keep the name", json.dumps(rec))
        self.assertNotIn("keep the name", log)
        self.assertIn("Follow-up 1", log)
        self.assertIn("not recorded", log)


class Scrub(unittest.TestCase):
    def test_scrub_removes_follow_up_text_from_published_records(self):
        rec, log, out = replay(ROWS)
        # A record published before the rule, as the hook once wrote it.
        rec["segments"][1]["prompt"] = "A, and keep the name"
        path = os.path.join(out, "commands", "runs.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps(rec) + "\n")
        with open(os.path.join(out, "commands", "log.md"), "w") as f:
            f.write("# Command log\n\n<!-- run:u1 -->\n`````text\nA, and keep the name\n`````\n<!-- /run:u1 -->\n")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=ROOT)
        subprocess.run([sys.executable, HOOK, "scrub", "--out", out], check=True, env=env, capture_output=True)
        rec2 = json.loads(open(path).readline())
        self.assertIsNone(rec2["segments"][1]["prompt"])
        log2 = open(os.path.join(out, "commands", "log.md")).read()
        self.assertNotIn("keep the name", log2)
        self.assertIn("not recorded", log2)


if __name__ == "__main__":
    unittest.main()
