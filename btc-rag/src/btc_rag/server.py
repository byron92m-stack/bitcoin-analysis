from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .llm import question_to_sql, format_answer
from .clickhouse import query, ClickHouseError

app = FastAPI(title="BTC-RAG", description="Bitcoin On-Chain Analytics Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class AskRequest(BaseModel):
    question: str

class AskResponse(BaseModel):
    question: str
    sql: str
    answer: str
    data: list[dict]

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="La pregunta no puede estar vacía")
    
    # 1. Traducir pregunta a SQL
    try:
        sql = question_to_sql(req.question)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar SQL: {e}")
    
    # 2. Ejecutar SQL en ClickHouse
    try:
        data = query(sql)
    except ClickHouseError as e:
        raise HTTPException(status_code=500, detail=f"Error en ClickHouse: {e}")
    
    # 3. Formatear respuesta
    try:
        answer = format_answer(req.question, sql, data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al formatear respuesta: {e}")
    
    return AskResponse(
        question=req.question,
        sql=sql,
        answer=answer,
        data=data
    )
