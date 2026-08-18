"""Network-free contracts for bounded extended ArcGIS evidence queries."""

import asyncio

from dp_lookup.clients.planning_evidence_queries import (
    MAX_CONCURRENT_LAYER_QUERIES,
    collect_planning_evidence,
)
from dp_lookup.planning_evidence import EvidenceMode, QueryState


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _ring(left=0, bottom=0, right=10, top=10):
    return [[left, bottom], [right, bottom], [right, top], [left, top], [left, bottom]]


def _feature(attributes, ring=None):
    return {"attributes": attributes, "geometry": {"rings": [ring or _ring()]}}


class Client:
    def __init__(self, layers):
        self.layers = layers
        self.payloads = {}
        self.active = 0
        self.max_active = 0

    async def post(self, url, *, data):
        layer_id = int(url.rsplit("/", 2)[-2])
        self.payloads[layer_id] = data
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.001)
        self.active -= 1
        payload = self.layers.get(layer_id, {"features": []})
        return Response(payload)


def test_standard_evidence_preserves_decisions_categories_and_authority_guards():
    client = Client(
        {
            83: {
                "features": [
                    _feature(
                        {
                            "OBJECTID": 10,
                            "EP_NO": "EP-T06",
                            "SANCTION_DECISIO": "Proposal refused; Section 26 provision reinstated",
                            "NOTIFICATION_NO": "TPB-1",
                            "GAZETTE_DATE": "07.10.2022",
                        }
                    )
                ]
            },
            2000: {
                "features": [
                    _feature(
                        {
                            "OBJECTID": 20,
                            "LABEL": "Test modification",
                            "NOTIFICATION_NO": "TEST-1",
                            "APPROVED_BY": "Test",
                            "APPROVAL_DOCUMENTS": "https://example.invalid/aprDocs/",
                        },
                        _ring(0, 0, 5, 10),
                    )
                ]
            },
            2250: {
                "features": [
                    _feature({"OBJECTID": 30, "CATEGORY": "CRZ II", "SUB_CATGORY": "CRZ II"}, _ring(0, 0, 5, 10)),
                    _feature({"OBJECTID": 31, "CATEGORY": "CRZ IB", "SUB_CATGORY": "CRZ IB"}, _ring(5, 0, 10, 10)),
                ]
            },
        }
    )

    report = asyncio.run(collect_planning_evidence(client, [_ring()], "COLABA", EvidenceMode.STANDARD))

    assert report.complete is True
    assert client.max_active <= MAX_CONCURRENT_LAYER_QUERIES
    assert 13 not in client.payloads
    assert all(payload["outFields"] != "*" for payload in client.payloads.values())
    ep = next(finding for finding in report.findings if finding.layer_id == 83)
    assert ep.attributes["SANCTION_DECISIO"].startswith("Proposal refused")
    assert ep.evidence_class.value == "statutory"
    test_record = next(finding for finding in report.findings if finding.layer_id == 2000)
    assert test_record.evidence_class.value == "regulatory"
    assert any("test approver" in warning for warning in test_record.warnings)
    assert {item["category"] for item in report.summary["crz_categories"]} == {"CRZ II", "CRZ IB"}


def test_malformed_and_truncated_layers_are_audited_without_becoming_absent():
    client = Client(
        {
            92: {"features": "not-a-list"},
            81: {"features": [], "exceededTransferLimit": True},
        }
    )

    report = asyncio.run(collect_planning_evidence(client, [_ring()], "WORLI", EvidenceMode.SHADOW))
    by_layer = {outcome.layer_id: outcome for outcome in report.outcomes}

    assert report.complete is False
    assert by_layer[92].state is QueryState.MALFORMED
    assert by_layer[81].state is QueryState.TRUNCATED
    assert by_layer[92].state is not QueryState.NOT_PRESENT
    assert by_layer[81].state is not QueryState.NOT_PRESENT


def test_one_transport_failure_does_not_discard_other_layer_outcomes():
    class FailingClient(Client):
        async def post(self, url, *, data):
            if url.endswith("/92/query"):
                raise RuntimeError("source timeout")
            return await super().post(url, data=data)

    report = asyncio.run(collect_planning_evidence(FailingClient({}), [_ring()], "WORLI", EvidenceMode.STANDARD))
    by_layer = {outcome.layer_id: outcome for outcome in report.outcomes}

    assert report.complete is False
    assert by_layer[92].state is QueryState.FAILED
    assert by_layer[83].state is QueryState.NOT_PRESENT
    assert len(report.outcomes) == 8
