import os
import sqlite3
import httpx
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# --- PATRÓN: EXTERNAL CONFIGURATION STORE ---
DB_PATH = os.getenv("DATABASE_PATH", "finflow_local.db")
DEFAULT_BUDGET = float(os.getenv("MONTHLY_BUDGET_LIMIT", "5000.00"))

# --- PATRÓN: DTO (Data Transfer Objects) ---
class TransactionCreateDTO(BaseModel):
    title: str = Field(..., min_length=3, max_length=100, examples=["Licencias Cloud AWS"])
    amount: float = Field(..., gt=0, examples=[450.00])
    type: str = Field(..., pattern="^(INCOME|EXPENSE)$", examples=["EXPENSE"])
    category: str = Field(..., min_length=3, examples=["Infraestructura"])

class TransactionResponseDTO(TransactionCreateDTO):
    id: int
    created_at: str

class SummaryResponseDTO(BaseModel):
    total_income: float
    total_expenses: float
    net_balance: float
    budget_limit: float
    budget_usage_percent: float
    budget_alert: bool
    alert_message: str

class AIAnalysisRequestDTO(BaseModel):
    summary_data: SummaryResponseDTO
    recent_transactions: List[TransactionResponseDTO]

class AIAnalysisResponseDTO(BaseModel):
    ai_recommendation: str

# --- PATRÓN: REPOSITORY (Capa de Acceso a Datos) ---
class TransactionRepository:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    amount REAL NOT NULL,
                    type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def create(self, dto: TransactionCreateDTO) -> dict:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO transactions (title, amount, type, category, created_at) VALUES (?, ?, ?, ?, ?)",
                (dto.title, dto.amount, dto.type, dto.category, now)
            )
            conn.commit()
            return {**dto.model_dump(), "id": cursor.lastrowid, "created_at": now}

    def get_all(self, category: Optional[str] = None) -> List[dict]:
        with self._get_conn() as conn:
            if category and category != "TODAS":
                rows = conn.execute(
                    "SELECT * FROM transactions WHERE category = ? ORDER BY id DESC", (category,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM transactions ORDER BY id DESC").fetchall()
            return [dict(r) for r in rows]

    def delete_by_id(self, tx_id: int) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
            conn.commit()
            return cursor.rowcount > 0

    def ping(self) -> bool:
        with self._get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
            return True

# --- CAPA DE SERVICIO DE DOMINIO (Lógica de Negocio) ---
class FinanceService:
    def __init__(self, repo: TransactionRepository):
        self.repo = repo
        self.budget_limit = DEFAULT_BUDGET

    def register_transaction(self, dto: TransactionCreateDTO) -> TransactionResponseDTO:
        created = self.repo.create(dto)
        return TransactionResponseDTO(**created)

    def list_transactions(self, category: Optional[str] = None) -> List[TransactionResponseDTO]:
        rows = self.repo.get_all(category)
        return [TransactionResponseDTO(**r) for r in rows]

    def remove_transaction(self, tx_id: int) -> None:
        if not self.repo.delete_by_id(tx_id):
            raise HTTPException(status_code=404, detail="Transacción no encontrada")

    def calculate_summary(self) -> SummaryResponseDTO:
        all_tx = self.repo.get_all()
        income = sum(t["amount"] for t in all_tx if t["type"] == "INCOME")
        expenses = sum(t["amount"] for t in all_tx if t["type"] == "EXPENSE")
        usage = round((expenses / self.budget_limit) * 100, 2) if self.budget_limit > 0 else 0.0
        alert = usage >= 85.0
        msg = "⚠️ ALERTA CRÍTICA: Se ha superado el 85% del presupuesto mensual." if alert else "✅ Ejecución presupuestal dentro de los límites saludables."

        return SummaryResponseDTO(
            total_income=round(income, 2),
            total_expenses=round(expenses, 2),
            net_balance=round(income - expenses, 2),
            budget_limit=self.budget_limit,
            budget_usage_percent=usage,
            budget_alert=alert,
            alert_message=msg
        )

class AIFinanceService:
    def __init__(self):
        # Corrección aplicada: Usando host.docker.internal para conectar con el VPS host
        self.ai_endpoint = "http://host.docker.internal:5001/v1/chat/completions"
        
    async def analyze_budget(self, data: AIAnalysisRequestDTO) -> AIAnalysisResponseDTO:
        prompt = f"""
        Actúa como un director financiero corporativo.
        El presupuesto total mensual es: ${data.summary_data.budget_limit}
        Se ha gastado: ${data.summary_data.total_expenses} ({data.summary_data.budget_usage_percent}% del total).
        Las transacciones recientes son: {[t.title + ' ($' + str(t.amount) + ')' for t in data.recent_transactions]}
        
        Analiza brevemente esta situación y genera una recomendación ejecutiva concisa en máximo 3 oraciones.
        """
        
        payload = {
            "messages": [
                {"role": "system", "content": "Eres un asistente financiero de la plataforma FinFlow."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 300
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(self.ai_endpoint, json=payload)
                response.raise_for_status()
                result = response.json()
                
            return AIAnalysisResponseDTO(ai_recommendation=result["choices"][0]["message"]["content"])
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"AI Engine no disponible: {str(e)}")

# --- PATRÓN: DEPENDENCY INJECTION ---
def get_repository() -> TransactionRepository:
    return TransactionRepository()

def get_finance_service(repo: TransactionRepository = Depends(get_repository)) -> FinanceService:
    return FinanceService(repo)

def get_ai_service() -> AIFinanceService:
    return AIFinanceService()

# --- CAPA DE CONTROLADORES / API REST ---
app = FastAPI(
    title="FinFlow Cloud API",
    description="Arquitectura Modular Cloud-Native para Control Presupuestal",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/v1/health", tags=["Monitoreo Cloud"])
def health_check(repo: TransactionRepository = Depends(get_repository)):
    """Patrón Health Endpoint Monitoring para orquestadores Cloud."""
    db_ok = repo.ping()
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/api/v1/transactions", response_model=TransactionResponseDTO, status_code=status.HTTP_201_CREATED, tags=["Transacciones"])
def create_transaction(dto: TransactionCreateDTO, service: FinanceService = Depends(get_finance_service)):
    return service.register_transaction(dto)

@app.get("/api/v1/transactions", response_model=List[TransactionResponseDTO], tags=["Transacciones"])
def get_transactions(category: Optional[str] = Query(None), service: FinanceService = Depends(get_finance_service)):
    return service.list_transactions(category)

@app.get("/api/v1/summary", response_model=SummaryResponseDTO, tags=["Métricas y Presupuesto"])
def get_summary(service: FinanceService = Depends(get_finance_service)):
    return service.calculate_summary()

@app.delete("/api/v1/transactions/{tx_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Transacciones"])
def delete_transaction(tx_id: int, service: FinanceService = Depends(get_finance_service)):
    service.remove_transaction(tx_id)

@app.get("/api/v1/ai-insights", response_model=AIAnalysisResponseDTO, tags=["Inteligencia Artificial"])
async def get_ai_budget_insights(
    finance_service: FinanceService = Depends(get_finance_service),
    ai_service: AIFinanceService = Depends(get_ai_service)
):
    """Pide a Llama 3.1 que analice el estado actual de los gastos de FinFlow."""
    summary = finance_service.calculate_summary()
    transactions = finance_service.list_transactions()
    
    recent_tx = transactions[:5] 
    
    request_data = AIAnalysisRequestDTO(
        summary_data=summary,
        recent_transactions=recent_tx
    )
    
    return await ai_service.analyze_budget(request_data)