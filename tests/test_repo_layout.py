from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ["packages/panel-core", "packages/panel-db", "apps/panel-api"]


def test_no_namespace_init() -> None:
    assert not list(ROOT.glob("*/*/src/payamakyar/__init__.py"))


def test_members_have_readme_and_tests() -> None:
    for m in MEMBERS:
        assert (ROOT / m / "README.md").is_file()
        assert (ROOT / m / "tests").is_dir()
