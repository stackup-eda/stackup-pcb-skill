"""Keep documented examples honest: the Stackup example in references/stackup.md must pass
`stackup check --locked` against the pinned library. Skipped when the Stackup CLI isn't installed.
Needs network the first time (Stackup downloads the pinned library into the temp dir's cache)."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
STACKUP_DOC = os.path.join(ROOT, "skills", "pcb-design", "references", "stackup.md")
MANIFEST = os.path.join(ROOT, "evals", "files", "latch", "manifest.kdl")


def kdl_blocks(markdown):
    return re.findall(r"```kdl\n(.*?)```", markdown, re.DOTALL)


class ExtractTests(unittest.TestCase):
    def test_doc_has_one_full_design_example(self):
        designs = [b for b in kdl_blocks(open(STACKUP_DOC).read()) if re.search(r"^design ", b, re.M)]
        self.assertEqual(len(designs), 1)
        self.assertIn("use \"@stackup/", designs[0])


@unittest.skipUnless(shutil.which("stackup"), "Stackup CLI not installed")
class StackupExampleTests(unittest.TestCase):
    def test_example_checks_clean(self):
        design = next(b for b in kdl_blocks(open(STACKUP_DOC).read())
                      if re.search(r"^design ", b, re.M))
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(MANIFEST, os.path.join(d, "manifest.kdl"))
            with open(os.path.join(d, "board.kdl"), "w") as f:
                f.write(design)
            result = subprocess.run(["stackup", "check", "board.kdl", "--locked"], cwd=d,
                                    capture_output=True, text=True)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertRegex(output, r"0 errors, 0 warnings, 0 notes", output)


if __name__ == "__main__":
    unittest.main()
