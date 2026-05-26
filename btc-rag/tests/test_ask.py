import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.btc_rag.server import app

client = TestClient(app)

# ============================================================
# HEALTH
# ============================================================
def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

# ============================================================
# ASK — casos normales
# ============================================================
@patch("src.btc_rag.server.query")
@patch("src.btc_rag.server.question_to_sql")
@patch("src.btc_rag.server.format_answer")
def test_ask_simple(mock_format, mock_sql, mock_query):
    mock_sql.return_value = "SELECT max(fees_btc) FROM block_metrics"
    mock_query.return_value = [{"max(fees_btc)": 1369.48}]
    mock_format.return_value = "El máximo de fees fue 1,369.48 BTC"
    
    resp = client.post("/ask", json={"question": "¿Cuál fue el día con más fees?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["question"] == "¿Cuál fue el día con más fees?"
    assert "SELECT" in data["sql"]
    assert "1,369.48" in data["answer"]

@patch("src.btc_rag.server.query")
@patch("src.btc_rag.server.question_to_sql")
@patch("src.btc_rag.server.format_answer")
def test_ask_with_date(mock_format, mock_sql, mock_query):
    mock_sql.return_value = "SELECT sum(fees_btc) FROM block_metrics WHERE toDate(toDateTime(time)) = '2017-12-22'"
    mock_query.return_value = [{"sum(fees_btc)": 1369.48}]
    mock_format.return_value = "El 22 de diciembre de 2017 se pagaron 1,369.48 BTC"
    
    resp = client.post("/ask", json={"question": "¿Fees del 22 de diciembre 2017?"})
    assert resp.status_code == 200
    assert "1,369.48" in resp.json()["answer"]

@patch("src.btc_rag.server.query")
@patch("src.btc_rag.server.question_to_sql")
@patch("src.btc_rag.server.format_answer")
def test_ask_numeric(mock_format, mock_sql, mock_query):
    mock_sql.return_value = "SELECT avg(close) FROM btc_1d"
    mock_query.return_value = [{"avg(close)": 45000.0}]
    mock_format.return_value = "El precio promedio es $45,000"
    
    resp = client.post("/ask", json={"question": "¿Precio promedio de BTC?"})
    assert resp.status_code == 200
    assert resp.json()["data"] == [{"avg(close)": 45000.0}]

# ============================================================
# ASK — sin datos
# ============================================================
@patch("src.btc_rag.server.query")
@patch("src.btc_rag.server.question_to_sql")
@patch("src.btc_rag.server.format_answer")
def test_ask_no_data(mock_format, mock_sql, mock_query):
    mock_sql.return_value = "SELECT * FROM block_metrics WHERE height = -1"
    mock_query.return_value = []
    mock_format.return_value = "No se encontraron datos para esa consulta."
    
    resp = client.post("/ask", json={"question": "¿Bloque -1?"})
    assert resp.status_code == 200
    assert "No se encontraron" in resp.json()["answer"]

# ============================================================
# ERRORES
# ============================================================
def test_ask_empty_question():
    resp = client.post("/ask", json={"question": ""})
    assert resp.status_code == 422

def test_ask_missing_question():
    resp = client.post("/ask", json={})
    assert resp.status_code == 422

@patch("src.btc_rag.server.question_to_sql")
def test_ask_openai_timeout(mock_sql):
    mock_sql.side_effect = TimeoutError("Timeout")
    resp = client.post("/ask", json={"question": "¿Día con más fees?"})
    assert resp.status_code == 500
    assert "Error al generar SQL" in resp.json()["detail"]

@patch("src.btc_rag.server.question_to_sql")
@patch("src.btc_rag.server.query")
def test_ask_clickhouse_error(mock_query, mock_sql):
    mock_sql.return_value = "INVALID SQL"
    from src.btc_rag.clickhouse import ClickHouseError
    mock_query.side_effect = ClickHouseError("Connection refused")
    resp = client.post("/ask", json={"question": "¿Test?"})
    assert resp.status_code == 500
    assert "Error en ClickHouse" in resp.json()["detail"]

@patch("src.btc_rag.server.question_to_sql")
@patch("src.btc_rag.server.query")
@patch("src.btc_rag.server.format_answer")
def test_ask_format_error(mock_format, mock_query, mock_sql):
    mock_sql.return_value = "SELECT 1"
    mock_query.return_value = [{"1": 1}]
    mock_format.side_effect = RuntimeError("Format error")
    resp = client.post("/ask", json={"question": "¿Test?"})
    assert resp.status_code == 500

# ============================================================
# FORMATO JSON
# ============================================================
@patch("src.btc_rag.server.query")
@patch("src.btc_rag.server.question_to_sql")
@patch("src.btc_rag.server.format_answer")
def test_response_json_format(mock_format, mock_sql, mock_query):
    mock_sql.return_value = "SELECT 1"
    mock_query.return_value = [{"1": 1}]
    mock_format.return_value = "Respuesta"
    
    resp = client.post("/ask", json={"question": "¿Test?"})
    data = resp.json()
    assert "question" in data
    assert "sql" in data
    assert "answer" in data
    assert "data" in data
    assert isinstance(data["data"], list)

# ============================================================
# CORS
# ============================================================
def test_cors_headers():
    resp = client.options("/ask")
    assert resp.status_code in [200, 405]

# ============================================================
# MÚLTIPLES PREGUNTAS
# ============================================================
@patch("src.btc_rag.server.query")
@patch("src.btc_rag.server.question_to_sql")
@patch("src.btc_rag.server.format_answer")
def test_multiple_questions(mock_format, mock_sql, mock_query):
    mock_sql.return_value = "SELECT 1"
    mock_query.return_value = [{"1": 1}]
    mock_format.return_value = "OK"
    
    for i in range(3):
        resp = client.post("/ask", json={"question": f"Pregunta {i}"})
        assert resp.status_code == 200

# ============================================================
# CARACTERES ESPECIALES
# ============================================================
@patch("src.btc_rag.server.query")
@patch("src.btc_rag.server.question_to_sql")
@patch("src.btc_rag.server.format_answer")
def test_special_characters(mock_format, mock_sql, mock_query):
    mock_sql.return_value = "SELECT 1"
    mock_query.return_value = [{"1": 1}]
    mock_format.return_value = "OK"
    
    resp = client.post("/ask", json={"question": "¿Cuántos fees en 2017? ¿Y en 2021?"})
    assert resp.status_code == 200

# ============================================================
# PREGUNTA LARGA
# ============================================================
@patch("src.btc_rag.server.query")
@patch("src.btc_rag.server.question_to_sql")
@patch("src.btc_rag.server.format_answer")
def test_long_question(mock_format, mock_sql, mock_query):
    mock_sql.return_value = "SELECT 1"
    mock_query.return_value = [{"1": 1}]
    mock_format.return_value = "OK"
    
    long_q = "¿Puedes decirme cuál fue el día con más fees en toda la historia de Bitcoin considerando solo la era Binance desde 2017?"
    resp = client.post("/ask", json={"question": long_q})
    assert resp.status_code == 200

# ============================================================
# RESPUESTA GRANDE
# ============================================================
@patch("src.btc_rag.server.query")
@patch("src.btc_rag.server.question_to_sql")
@patch("src.btc_rag.server.format_answer")
def test_large_response(mock_format, mock_sql, mock_query):
    mock_sql.return_value = "SELECT * FROM btc_1d"
    mock_query.return_value = [{"date": f"2020-01-{i:02d}", "close": 10000 + i} for i in range(1, 100)]
    mock_format.return_value = "Muchos datos"
    
    resp = client.post("/ask", json={"question": "¿Todos los precios?"})
    assert resp.status_code == 200

# ============================================================
# CONCURRENCIA (simulada con requests secuenciales)
# ============================================================
@patch("src.btc_rag.server.query")
@patch("src.btc_rag.server.question_to_sql")
@patch("src.btc_rag.server.format_answer")
def test_concurrent(mock_format, mock_sql, mock_query):
    mock_sql.return_value = "SELECT 1"
    mock_query.return_value = [{"1": 1}]
    mock_format.return_value = "OK"
    
    # Dos requests seguidos
    r1 = client.post("/ask", json={"question": "Q1"})
    r2 = client.post("/ask", json={"question": "Q2"})
    assert r1.status_code == 200
    assert r2.status_code == 200

