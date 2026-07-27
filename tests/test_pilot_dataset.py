import json
import zipfile

from src.data.aihub_71748_tokenizer_corpus import CorpusBuildConfig
from src.data.pilot_dataset import PilotDatasetConfig, _iter_source_records, pii_categories


def test_pii_detector_reports_categories_without_values():
    assert pii_categories("synthetic@example.invalid") == ("email",)
    assert pii_categories("안전한 합성 문장") == ()


def test_pilot_dataset_config_is_bounded():
    PilotDatasetConfig().validate()


def test_canonical_selector_stops_archive_after_byte_quota(monkeypatch, tmp_path):
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("a.json", json.dumps({"data_info": [{"contents": "12345"}, {"contents": "too-large"}]}))
        zipped.writestr("b.json", json.dumps({"data_info": [{"contents": "x"}]}))
    row = {"path": archive, "relative_path": "Training/01.원천데이터/TS_01.synthetic.zip"}
    monkeypatch.setattr("src.data.pilot_dataset._eligible_archives", lambda *_args: [row])
    monkeypatch.setattr("src.data.pilot_dataset.CorpusBuildConfig", lambda: CorpusBuildConfig(records_per_archive=10, bytes_per_archive=8, max_record_bytes=1024))
    canonical = list(_iter_source_records(tmp_path, tmp_path / "inventory.yaml"))
    legacy = list(_iter_source_records(tmp_path, tmp_path / "inventory.yaml", legacy_continue_after_byte_quota=True))
    assert len(canonical) == 1
    assert len(legacy) == 2
    assert {item["source_id"] for item in canonical}.issubset({item["source_id"] for item in legacy})


def test_selector_normalization_dedup_and_identity_are_deterministic(monkeypatch, tmp_path):
    archive = tmp_path / "source.zip"
    document = {"data_info": [{"contents": "value  \r\n"}, {"contents": "value\n"}, {"contents": None}, {"contents": "   "}]}
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("a.json", json.dumps(document))
    row = {"path": archive, "relative_path": "Training/01.원천데이터/TS_01.synthetic.zip"}
    monkeypatch.setattr("src.data.pilot_dataset._eligible_archives", lambda *_args: [row])
    first = list(_iter_source_records(tmp_path, tmp_path / "inventory.yaml"))
    second = list(_iter_source_records(tmp_path, tmp_path / "inventory.yaml"))
    assert len(first) == 1
    assert [(item["source_id"], item["document_id"]) for item in first] == [
        (item["source_id"], item["document_id"]) for item in second
    ]
    assert first[0]["raw_sha256"] != first[0]["document_id"]
