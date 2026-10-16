"""Transcripts are read incrementally: a cache remembers how far each one was read, so a
command reads only what was appended since. Every answer must match a full read."""
import json
import os
import re
import stat

from helpers import Sandbox, load, uuid

USER_SAYS_TITLE = {"type": "user", "message": {"content": 'a "custom-title" and an "ai-title", in prose'}}


class TestTranscriptCache(Sandbox):
    def add(self, path, *recs, newline=True):
        with open(path, "a") as f:
            f.write("\n".join(json.dumps(r) for r in recs) + ("\n" if newline else ""))

    def full(self, path):
        """What a fresh module with no cache reads: the whole file."""
        return load(dict(self.env, CLAUDE_BARDO_DIR=os.path.join(self.tmp, "nocache"))).transcript_meta(path)

    def entry(self, path):
        return self.m.TRANSCRIPTS.files.get(path)

    def test_appends_are_read_and_match_a_full_read(self):
        cwd = self.workdir()
        p = self.transcript(uuid(1), cwd, [{"type": "ai-title", "aiTitle": "A"}])
        self.assertEqual(self.m.transcript_meta(p), {"cwd": cwd, "custom_title": None, "ai_title": "A"})
        self.add(p, {"type": "custom-title", "customTitle": "Mine"}, USER_SAYS_TITLE, {"type": "ai-title", "aiTitle": "B"})
        got = self.m.transcript_meta(p)
        self.assertEqual(got, {"cwd": cwd, "custom_title": "Mine", "ai_title": "B"})
        self.assertEqual(got, self.full(p))
        self.assertEqual(self.entry(p)["off"], os.path.getsize(p))

    def test_the_cache_survives_the_process(self):
        cwd = self.workdir()
        p = self.transcript(uuid(1), cwd, [{"type": "custom-title", "customTitle": "Mine"}])
        self.m.transcript_meta(p)
        self.m.TRANSCRIPTS.save()
        self.assertEqual(stat.S_IMODE(os.stat(self.m.TRANSCRIPT_CACHE).st_mode), 0o600)
        later = load(self.env)
        self.add(p, {"type": "ai-title", "aiTitle": "C"})
        self.assertEqual(later.transcript_meta(p), {"cwd": cwd, "custom_title": "Mine", "ai_title": "C"})
        self.assertEqual(later.transcript_meta(p), self.full(p))

    def test_what_was_read_is_not_read_again(self):
        p = self.transcript(uuid(1), self.workdir(), [{"type": "ai-title", "aiTitle": "AAAA"}, USER_SAYS_TITLE])
        self.m.transcript_meta(p)
        with open(p, "r+b") as f:                     # same size, same inode, before the mark: only a reread sees it
            data = f.read().replace(b"AAAA", b"ZZZZ")
            f.seek(0)
            f.write(data)
        self.assertEqual(self.m.transcript_meta(p)["ai_title"], "AAAA")

    def test_a_line_still_being_written(self):
        p = self.transcript(uuid(1), self.workdir())
        self.add(p, {"type": "ai-title", "aiTitle": "D"}, newline=False)
        self.assertEqual(self.m.transcript_meta(p)["ai_title"], "D")          # as a full read would say
        self.assertLess(self.entry(p)["off"], os.path.getsize(p))              # but not cached as read
        with open(p, "a") as f:                                                # the writer finishes the line
            f.write("\n" + json.dumps({"type": "ai-title", "aiTitle": "E"}) + "\n")
        self.assertEqual(self.m.transcript_meta(p)["ai_title"], "E")
        self.assertEqual(self.m.transcript_meta(p), self.full(p))

    def test_a_rewritten_transcript_is_read_from_the_start(self):
        cwd = self.workdir()
        p = self.transcript(uuid(1), cwd, [{"type": "ai-title", "aiTitle": "old"}, USER_SAYS_TITLE])
        self.m.transcript_meta(p)
        self.transcript(uuid(1), cwd, [{"type": "ai-title", "aiTitle": "new"}])          # shorter
        self.assertEqual(self.m.transcript_meta(p)["ai_title"], "new")
        self.transcript(uuid(1), cwd, [{"type": "ai-title", "aiTitle": "longer"}] * 3)   # longer, same inode
        self.assertEqual(self.m.transcript_meta(p), self.full(p))
        os.remove(p)                                                                       # another inode
        self.transcript(uuid(1), cwd, [{"type": "ai-title", "aiTitle": "replaced"}])
        self.assertEqual(self.m.transcript_meta(p)["ai_title"], "replaced")

    def test_a_broken_cache_costs_only_a_full_read(self):
        p = self.transcript(uuid(1), self.workdir(), [{"type": "ai-title", "aiTitle": "A"}])
        os.makedirs(self.state, exist_ok=True)
        with open(os.path.join(self.state, "transcripts.json"), "w") as f:
            f.write('{"v": 1, "files": {"%s": {"ino": "x", "off": -5, "cwd": 3}}}' % p)
        fresh = load(self.env)
        self.assertEqual(fresh.transcript_meta(p), self.full(p))

    def test_gone_transcripts_leave_the_cache(self):
        p = self.transcript(uuid(1), self.workdir())
        q = self.transcript(uuid(2), self.workdir("other"))
        self.m.transcript_meta(p)
        self.m.transcript_meta(q)
        os.remove(q)
        self.m.TRANSCRIPTS.save()
        with open(self.m.TRANSCRIPT_CACHE) as f:
            self.assertEqual(list(json.load(f)["files"]), [p])

    def test_list_writes_the_cache_and_answers_the_same_twice(self):
        cwd = self.workdir()
        self.transcript(uuid(1), cwd, [{"type": "ai-title", "aiTitle": "alpha"}])
        self.start(uuid(1), cwd)
        self.end(uuid(1), "other")
        def ageless(out):
            return re.sub(r"\b\d+[smhd]\b", "<age>", out)        # a second may tick between the runs
        first = self.run_tool("list")
        self.assertTrue(os.path.isfile(os.path.join(self.state, "transcripts.json")))
        self.assertEqual(ageless(self.run_tool("list").stdout), ageless(first.stdout))
        self.assertIn("alpha", first.stdout)
        self.assertEqual(first.stderr, "")                  # no terminal here: no progress line
