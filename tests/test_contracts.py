import json
from pathlib import Path

import jsonschema
import pytest

from crm_workflow.models import CaseResponse, OrderRequest


def test_versioned_json_schemas_are_valid_and_closed():
    folder = Path(__file__).resolve().parents[1] / "contracts" / "v1"
    schemas = list(folder.glob("*.schema.json"))
    assert len(schemas) >= 10
    for path in schemas:
        schema = json.loads(path.read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False, path
        assert schema["$id"].startswith("urn:p06:v1:")


def test_request_rejects_unversioned_extensions_and_new_mutation_fields():
    schema = OrderRequest.model_json_schema()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"message_id": "version-test", "discount": 50, "actor_id": "executor"}, schema)


def test_original_smoke_response_validates_against_versioned_business_contract():
    path = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "local-smoke.json"
    response = json.loads(path.read_text())["case"]
    model = CaseResponse.model_validate(response)
    assert model.state == "COMPLETED"
    assert model.tenant_id == model.plan.tenant_id
