"""Tests for Airflow DAGs and ControlTowerClient integration."""

import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dags.utils.control_tower_client import ControlTowerClient  # noqa: E402

DAGS_DIR = REPO_ROOT / "dags"


def test_control_tower_client_type_b_sync():
    """Verify Type B sync triggers the expected POST endpoint."""
    client = ControlTowerClient(base_url="http://test-server:8000")
    fake_response = {
        "status": "completed",
        "results": [
            {
                "carrier": "Carrier B1",
                "total_fetched": 10,
                "normalized": 10,
                "anomalies": 0,
                "errors": 0,
            }
        ],
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response

    mock_requests = MagicMock()
    mock_requests.post.return_value = mock_resp

    with patch("dags.utils.control_tower_client.requests", mock_requests):
        res = client.trigger_type_b_sync(carrier_name="Carrier B1")
        assert res["status"] == "completed"
        assert len(res["results"]) == 1
        mock_requests.post.assert_called_once()
        args, kwargs = mock_requests.post.call_args
        assert args[0] == "http://test-server:8000/api/v1/sync/type-b"
        assert kwargs["params"] == {"carrier_name": "Carrier B1"}


def test_control_tower_client_type_c_upload(tmp_path: Path):
    """Verify Type C file upload sends multipart data to sync endpoint."""
    test_file = tmp_path / "sample_batch.csv"
    test_file.write_text("tracking,status,timestamp\nTRK1,CREATED,2026-10-20T10:00:00Z\n")

    client = ControlTowerClient(base_url="http://test-server:8000")
    fake_response = {
        "status": "completed",
        "valid_rows_processed": 1,
        "anomalies_detected": 0,
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response

    mock_requests = MagicMock()
    mock_requests.post.return_value = mock_resp

    with patch("dags.utils.control_tower_client.requests", mock_requests):
        res = client.upload_type_c_file(
            file_path=test_file,
            carrier_name="TransExpress Logistics",
        )
        assert res["status"] == "completed"
        mock_requests.post.assert_called_once()
        args, kwargs = mock_requests.post.call_args
        assert args[0] == "http://test-server:8000/api/v1/sync/type-c/upload"
        assert kwargs["data"] == {"carrier_name": "TransExpress Logistics"}


def test_control_tower_client_health():
    """Verify health check probe against Control Tower backend."""
    client = ControlTowerClient(base_url="http://test-server:8000")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "healthy", "database": "connected"}

    mock_requests = MagicMock()
    mock_requests.get.return_value = mock_resp

    with patch("dags.utils.control_tower_client.requests", mock_requests):
        res = client.check_health()
        assert res["status"] == "healthy"
        mock_requests.get.assert_called_once_with(
            "http://test-server:8000/api/v1/health",
            headers={
                "Accept": "application/json",
                "User-Agent": "Airflow-ControlTower-Orchestrator/1.0",
            },
            timeout=10,
        )


def test_dag_type_c_structure_and_decorators():
    """Verify that dag_type_c_ingestion.py uses TaskFlow API and correct schedules."""
    dag_file = DAGS_DIR / "dag_type_c_ingestion.py"
    assert dag_file.is_file(), f"Missing DAG file: {dag_file}"

    tree = ast.parse(dag_file.read_text(encoding="utf-8"))

    # Verify no legacy PythonOperator imports or instantiations
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    ]
    assert "PythonOperator" not in imports
    assert "dag" in imports
    assert "task" in imports

    # Check that decorators are used on functions
    decorator_names = [
        d.id
        if isinstance(d, ast.Name)
        else d.func.id
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
        else ""
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for d in node.decorator_list
    ]
    assert "dag" in decorator_names
    assert "task" in decorator_names

    # Check schedule interval 0 */4 * * * in source
    content = dag_file.read_text(encoding="utf-8")
    assert 'schedule="0 */4 * * *"' in content
    assert '"type-c"' in content


def test_dag_type_b_structure_and_decorators():
    """Verify that dag_type_b_polling.py fulfills HU-27 / RIWI-135 requirements."""
    dag_file = DAGS_DIR / "dag_type_b_polling.py"
    assert dag_file.is_file(), f"Missing DAG file: {dag_file}"

    tree = ast.parse(dag_file.read_text(encoding="utf-8"))

    # Verify TaskFlow API
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    ]
    assert "PythonOperator" not in imports
    assert "dag" in imports
    assert "task" in imports

    content = dag_file.read_text(encoding="utf-8")
    # RIWI-136: 30-minute schedule
    assert 'schedule="*/30 * * * *"' in content
    # RIWI-137: Type B pull polling
    assert '"type_b_pull_polling"' in content
    # RIWI-138: Retries with exponential backoff
    assert '"retries": 3' in content
    assert '"retry_exponential_backoff": True' in content
