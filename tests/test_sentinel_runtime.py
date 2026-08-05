import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SentinelRuntimeTests(unittest.TestCase):
    def test_node_can_load_jsdom_dependency(self):
        result = subprocess.run(
            ["node", "-e", "require('jsdom')"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            0,
            (result.stderr or result.stdout or "Node 无法加载 jsdom").strip(),
        )


if __name__ == "__main__":
    unittest.main()
