import copy
import json
import os
import stat

import pytest
from pydantic import ValidationError

from app import config
from app.models.packet import Packet
from app.services.loader import _sha256, check_integrity, stage_packet


def test_counts_from_the_brief(idx):
    p = idx.packet
    assert len(p.documents) == 74
    assert len(p.extracted_values) == 3012
    assert len(p.return_versions) == 3
    assert [v.version for v in p.return_versions] == ["v1", "v2", "v3"]


def test_packet_is_internally_consistent(idx):
    assert check_integrity(idx.packet) == []


def test_staging_never_touches_the_original(tmp_path):
    before = _sha256(config.PACKET_SOURCE)
    target, sha = stage_packet(config.PACKET_SOURCE, tmp_path)
    assert sha == before == _sha256(config.PACKET_SOURCE) == _sha256(target)
    assert not os.stat(target).st_mode & stat.S_IWRITE  # working copy is read-only
    # staging again is idempotent
    stage_packet(config.PACKET_SOURCE, tmp_path)
    os.chmod(target, stat.S_IWRITE | stat.S_IREAD)


@pytest.fixture(scope="module")
def raw():
    return json.loads(config.PACKET_SOURCE.read_text(encoding="utf-8"))


def test_unknown_field_fails_loudly(raw):
    drifted = copy.deepcopy(raw)
    drifted["documents"][0]["new_pipeline_field"] = 1
    with pytest.raises(ValidationError):
        Packet.model_validate(drifted)


def test_wrong_type_fails_loudly(raw):
    drifted = copy.deepcopy(raw)
    drifted["extracted_values"][0]["confidence"] = 1.7
    with pytest.raises(ValidationError):
        Packet.model_validate(drifted)


def test_missing_document_is_caught_by_integrity_checks(raw):
    broken = copy.deepcopy(raw)
    broken["documents"].pop()
    fails = check_integrity(Packet.model_validate(broken))
    assert any("expected 74 documents" in f for f in fails)
    assert any("unknown document D74" in f for f in fails)
