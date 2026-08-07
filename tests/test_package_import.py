import subprocess
import sys
import unittest
from pathlib import Path


class PackageImportTest(unittest.TestCase):
    def test_drawing_graph_package_imports_without_runtime_side_effects(self):
        project_root = Path(__file__).resolve().parents[1]
        src_root = project_root / "src"
        data_root = project_root / "data"
        data_entries_before = sorted(path.name for path in data_root.iterdir())

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib, sys; "
                    f"sys.path.insert(0, {str(src_root)!r}); "
                    "package = importlib.import_module('drawing_graph'); "
                    "print(package.__name__); "
                    "print('neo4j' in sys.modules)"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        data_entries_after = sorted(path.name for path in data_root.iterdir())
        package_name, neo4j_loaded = result.stdout.strip().splitlines()

        self.assertEqual("drawing_graph", package_name)
        self.assertEqual(data_entries_before, data_entries_after)
        self.assertEqual("False", neo4j_loaded)


if __name__ == "__main__":
    unittest.main()
