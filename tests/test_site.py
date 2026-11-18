"""Test trang tĩnh: dựng HTML an toàn và lịch dựng lại (không gọi mạng)."""

import json
import unittest
from datetime import datetime

from brief import db, schedule, site
from brief.config import TZ

SET = {"site": {"enabled": True, "rebuild_at": ["08:25", "16:45"]}}


class SiteTests(unittest.TestCase):
    def test_render_embeds_data_safely(self):
        html = site.render({"news": {"items": [{"title": "</script><script>alert(1)</script>"}]}, "errors": {}})
        self.assertNotIn("/*__DATA__*/", html)
        self.assertEqual(html.count("</script>"), html.count("<script"))   # dữ liệu không đóng được thẻ script
        start = html.index('<script id="data" type="application/json">') + len('<script id="data" type="application/json">')
        end = html.index("</script>", start)
        self.assertEqual(json.loads(html[start:end])["news"]["items"][0]["title"], "</script><script>alert(1)</script>")

    def test_site_due_windows(self):
        d = datetime(2031, 3, 4, tzinfo=TZ)
        self.assertIsNone(schedule.site_due(d.replace(hour=8, minute=0), SET))
        k = schedule.site_due(d.replace(hour=8, minute=30), SET)
        self.assertEqual(k, "site:2031-03-04:08:25")
        db.kv_set(k, {"status": "done"})
        self.assertIsNone(schedule.site_due(d.replace(hour=9), SET))            # đã dựng mốc sáng
        self.assertEqual(schedule.site_due(d.replace(hour=17), SET), "site:2031-03-04:16:45")
        self.assertIsNone(schedule.site_due(d.replace(hour=17), {"site": {"enabled": False}}))



class PublishTests(unittest.TestCase):
    def test_publish_orphan_commit_and_skip_unchanged(self):
        import subprocess
        import tempfile
        from pathlib import Path
        from brief import publish
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            remote = t / "remote.git"
            subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
            sd = t / "site"
            sd.mkdir()
            (sd / "index.html").write_text("<html>v1</html>")
            (sd / "data.json").write_text(json.dumps({"generated_at": "15/11 16:45", "errors": {}}))
            cfg = {"site": {"publish": True, "publish_remote": str(remote), "publish_branch": "gh-pages"}}
            kw = dict(settings=cfg, site_dir=sd, repo_dir=t / "repo")
            self.assertEqual(publish.publish(**kw)["status"], "pushed")
            self.assertEqual(publish.publish(**kw)["status"], "unchanged")
            (sd / "index.html").write_text("<html>v2</html>")
            self.assertEqual(publish.publish(**kw)["status"], "pushed")
            git = ["git", "--git-dir", str(remote)]
            log = subprocess.run(git + ["rev-list", "gh-pages"], capture_output=True, text=True, check=True).stdout.split()
            self.assertEqual(len(log), 1)                                  # luôn chỉ 1 commit
            files = subprocess.run(git + ["ls-tree", "-r", "--name-only", "gh-pages"],
                                   capture_output=True, text=True, check=True).stdout.split()
            self.assertEqual(sorted(files), [".github/workflows/pages.yml", ".nojekyll", "README.md",
                                             "index.html", "publish.json"])
            body = subprocess.run(git + ["show", "gh-pages:index.html"], capture_output=True, text=True).stdout
            self.assertEqual(body, "<html>v2</html>")


if __name__ == "__main__":
    unittest.main()
