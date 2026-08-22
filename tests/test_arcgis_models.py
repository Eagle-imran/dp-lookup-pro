"""Boundary tests for typed ArcGIS response decoding."""

from dp_lookup.clients.arcgis_models import ArcGISPayload, decode_arcgis_response


class Response:
    status_code = 200

    def __init__(self, value):
        self.value = value

    def json(self):
        return self.value


def test_typed_payload_preserves_valid_features_and_identify_results():
    payload = decode_arcgis_response(
        Response(
            {
                "features": [{"attributes": {"OBJECTID": 7}, "geometry": {"rings": [[[0, 0]]]}}],
                "results": [{"layerId": "13", "attributes": {"CTS_CS_NO": "733"}}],
            }
        )
    )

    assert payload is not None
    assert payload.features_valid is True
    assert payload.results_valid is True
    assert payload.features[0].attributes["OBJECTID"] == 7
    assert payload.results[0].layer_id == 13


def test_typed_payload_distinguishes_empty_from_malformed_collections():
    empty = ArcGISPayload.from_mapping({})
    malformed = ArcGISPayload.from_mapping({"features": {}, "results": "bad"})

    assert empty is not None and empty.features_valid and empty.results_valid
    assert malformed is not None
    assert malformed.features == () and malformed.results == ()
    assert malformed.features_valid is False and malformed.results_valid is False


def test_decoder_rejects_http_errors_arcgis_errors_and_non_objects():
    failed = Response({"features": []})
    failed.status_code = 503

    assert decode_arcgis_response(failed) is None
    assert decode_arcgis_response(Response({"error": {"message": "bad query"}})) is None
    assert decode_arcgis_response(Response([])) is None
