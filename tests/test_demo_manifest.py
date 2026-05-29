import json
import warnings
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_demo_manifest_exists_and_valid_json() -> None:
    manifest = load_json(DEMO_DIR / "demo_manifest.json")

    assert manifest["schema_version"] == "1.2.0"
    assert "main_demo" in manifest
    assert "backup_demo" in manifest


def test_demo_manifest_has_required_batch_3_fields() -> None:
    manifest = load_json(DEMO_DIR / "demo_manifest.json")
    required = {
        "task_id",
        "title",
        "is_demo",
        "primary",
        "audience_note",
        "recommended_tab_order",
    }

    for key in ("main_demo", "backup_demo"):
        demo = manifest[key]
        assert required <= set(demo)
        assert isinstance(demo["task_id"], str) and demo["task_id"].startswith("T-")
        assert demo["is_demo"] is True
        assert isinstance(demo["recommended_tab_order"], list)
        assert demo["recommended_tab_order"]

    assert manifest["main_demo"]["primary"] is True
    assert manifest["backup_demo"]["primary"] is False


def test_demo_case_configs_valid() -> None:
    for filename in ("main_case.json", "backup_case.json"):
        case = load_json(DEMO_DIR / filename)
        assert case["query"]
        assert case["competitors_cli"]
        assert isinstance(case["expected_artifacts"], list)
        assert "claims.json" in case["expected_artifacts"]
        assert "evidence.json" in case["expected_artifacts"]
        assert "trace.json" in case["expected_artifacts"]


def test_demo_manifest_task_ids_exist_when_runs_are_present() -> None:
    manifest = load_json(DEMO_DIR / "demo_manifest.json")
    runs_dir = ROOT / "runs"
    missing = [
        demo["task_id"]
        for demo in (manifest["main_demo"], manifest["backup_demo"])
        if not (runs_dir / demo["task_id"]).exists()
    ]

    if missing:
        warnings.warn(
            "Demo run artifacts are not present in this checkout: " + ", ".join(missing),
            stacklevel=2,
        )


def test_demo_scripts_reference_manifest_and_serve_command() -> None:
    for filename in ("run_demo.sh", "run_demo.ps1"):
        text = (DEMO_DIR / filename).read_text(encoding="utf-8")
        assert "demo_manifest.json" in text
        assert "python -m cs_mvp.cli serve" in text


def test_readme_and_demo_guide_reference_demo_task_ids() -> None:
    manifest = load_json(DEMO_DIR / "demo_manifest.json")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "DEMO_GUIDE.md").read_text(encoding="utf-8")

    for demo in (manifest["main_demo"], manifest["backup_demo"]):
        assert demo["task_id"] in readme
        assert demo["task_id"] in guide


def test_readme_covers_topic_alignment_keywords() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    keywords = [
        "多个专职 Agent 协作",
        "DAG 式任务流转",
        "交叉审查反馈闭环",
        "自定义竞品知识 Schema",
        "公开信息采集",
        "结果溯源",
        "系统可观测性",
    ]

    for keyword in keywords:
        assert keyword in readme
