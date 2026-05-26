import subprocess
import json
from .schema import SCHEMA_PROMPT

MODEL = "opencode/deepseek-v4-flash-free"
TIMEOUT = 30

def question_to_sql(question: str) -> str:
    """Traduce pregunta en español a SQL usando OpenCode + DeepSeek Flash FREE."""
    prompt = SCHEMA_PROMPT + f"\n\nPregunta: {question}\n\nSQL:"
    
    result = subprocess.run(
        ["opencode", "run", "--model", MODEL, prompt],
        capture_output=True, text=True, timeout=TIMEOUT
    )
    
    sql = result.stdout.strip()
    
    # Limpiar markdown si el modelo lo devuelve
    if sql.startswith("```"):
        sql = sql.split("\n")[1:-1]
        sql = "\n".join(sql)
    
    # Quitar ; final si tiene
    sql = sql.rstrip(";").strip()
    
    return sql


def format_answer(question: str, sql: str, data: list[dict]) -> str:
    """Formatea la respuesta en lenguaje natural."""
    if not data:
        return "No se encontraron datos para esa consulta."
    
    prompt = f"""Pregunta del usuario: {question}

SQL ejecutado: {sql}

Datos obtenidos (JSON): {json.dumps(data, indent=2, default=str)}

Respondé en español en una frase clara y concisa. Solo la respuesta, sin introducciones."""
    
    result = subprocess.run(
        ["opencode", "run", "--model", MODEL, prompt],
        capture_output=True, text=True, timeout=TIMEOUT
    )
    
    return result.stdout.strip()
