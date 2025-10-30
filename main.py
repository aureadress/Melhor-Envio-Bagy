from flask import Flask, request, jsonify
import requests
import os
import datetime
import sqlite3
import threading
import time
import logging
import re
from typing import Optional, Dict, Any, List, Tuple
from functools import wraps

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# === CONFIGURAÇÕES ===
BAGY_TOKEN = os.getenv("BAGY_TOKEN")
MELHORENVIO_TOKEN = os.getenv("MELHORENVIO_TOKEN")

BAGY_BASE = os.getenv("BAGY_BASE", "https://api.dooca.store")
MELHORENVIO_BASE = os.getenv("MELHORENVIO_BASE", "https://melhorenvio.com.br/api/v2")

# Configurações do remetente
SENDER_NAME = os.getenv("SENDER_NAME", "Loja Aurea Dress")
SENDER_PHONE = os.getenv("SENDER_PHONE", "11999999999")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "contato@aureadress.com")
SENDER_DOCUMENT = os.getenv("SENDER_DOCUMENT", "")
SENDER_ADDRESS = os.getenv("SENDER_ADDRESS", "Rua Exemplo, 123")
SENDER_COMPLEMENT = os.getenv("SENDER_COMPLEMENT", "")
SENDER_NUMBER = os.getenv("SENDER_NUMBER", "123")
SENDER_DISTRICT = os.getenv("SENDER_DISTRICT", "Centro")
SENDER_CITY = os.getenv("SENDER_CITY", "São Paulo")
SENDER_STATE = os.getenv("SENDER_STATE", "SP")
SENDER_ZIPCODE = os.getenv("SENDER_ZIPCODE", "03320-001")

# Configurações do serviço
# SERVICE_ID padrão = 2 (SEDEX) - mais amplamente aceito, pode ser alterado na plataforma Melhor Envio depois
# Opções: 1=PAC, 2=SEDEX, 3=PAC Mini, etc
SERVICE_ID = int(os.getenv("SERVICE_ID", "2"))  # SEDEX como padrão
TRACKER_INTERVAL = int(os.getenv("TRACKER_INTERVAL", "600"))
DB_PATH = os.getenv("DB_PATH", "data.db")

MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))

# Validação de configurações críticas
if not BAGY_TOKEN:
    logger.warning("⚠️  BAGY_TOKEN não configurado! A integração não funcionará.")
if not MELHORENVIO_TOKEN:
    logger.warning("⚠️  MELHORENVIO_TOKEN não configurado! A integração não funcionará.")

service_names = {1: "PAC", 2: "SEDEX", 3: "PAC Mini"}
logger.info(f"🔧 Configurações carregadas: SENDER_ZIPCODE={SENDER_ZIPCODE}, SERVICE_ID={SERVICE_ID} ({service_names.get(SERVICE_ID, 'Desconhecido')})")
logger.info(f"ℹ️  O método de envio pode ser alterado posteriormente na plataforma Melhor Envio")

# === FUNÇÕES AUXILIARES ===
def clean_document(document: str) -> str:
    """Remove caracteres não numéricos de um documento (CPF/CNPJ)."""
    if not document:
        return ""
    return re.sub(r'[^0-9]', '', str(document))

def validate_cpf(cpf: str) -> bool:
    """Valida um CPF brasileiro."""
    cpf = clean_document(cpf)
    
    # CPF deve ter 11 dígitos
    if len(cpf) != 11:
        return False
    
    # CPF não pode ter todos os dígitos iguais
    if cpf == cpf[0] * 11:
        return False
    
    # Validar primeiro dígito verificador
    sum_dig1 = sum(int(cpf[i]) * (10 - i) for i in range(9))
    dig1 = 11 - (sum_dig1 % 11)
    dig1 = 0 if dig1 >= 10 else dig1
    
    if dig1 != int(cpf[9]):
        return False
    
    # Validar segundo dígito verificador
    sum_dig2 = sum(int(cpf[i]) * (11 - i) for i in range(10))
    dig2 = 11 - (sum_dig2 % 11)
    dig2 = 0 if dig2 >= 10 else dig2
    
    if dig2 != int(cpf[10]):
        return False
    
    return True

def clean_zipcode(zipcode: str) -> str:
    """Remove caracteres não numéricos de um CEP."""
    if not zipcode:
        return ""
    return re.sub(r'[^0-9]', '', str(zipcode))

# === BANCO LOCAL (SQLite) ===
def db_init():
    """Inicializa o banco de dados SQLite com a estrutura necessária."""
    try:
        with sqlite3.connect(DB_PATH) as con:
            con.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bagy_order_id TEXT UNIQUE NOT NULL,
                melhorenvio_order_id TEXT,
                tracking_code TEXT,
                status TEXT NOT NULL DEFAULT 'created',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                delivered_at TEXT,
                retry_count INTEGER DEFAULT 0,
                last_error TEXT
            )""")
            con.execute("""
            CREATE INDEX IF NOT EXISTS idx_status ON orders(status)
            """)
            con.execute("""
            CREATE INDEX IF NOT EXISTS idx_tracking ON orders(tracking_code)
            """)
            con.commit()
        logger.info(f"✅ Banco de dados inicializado: {DB_PATH}")
    except Exception as e:
        logger.error(f"❌ Erro ao inicializar banco de dados: {e}")
        raise

db_init()

def db_save(order_id: str, me_order_id: Optional[str] = None, tracking: Optional[str] = None, 
            status: str = "created", error: Optional[str] = None):
    """Salva ou atualiza um pedido no banco de dados."""
    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.execute("SELECT retry_count FROM orders WHERE bagy_order_id = ?", (order_id,))
            existing = cur.fetchone()
            retry_count = (existing[0] if existing else 0) + (1 if error else 0)
            
            con.execute("""
            INSERT INTO orders(bagy_order_id, melhorenvio_order_id, tracking_code, status, retry_count, last_error, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(bagy_order_id) DO UPDATE SET
                melhorenvio_order_id = COALESCE(?, melhorenvio_order_id),
                tracking_code = COALESCE(?, tracking_code),
                status = ?,
                retry_count = ?,
                last_error = ?,
                updated_at = CURRENT_TIMESTAMP,
                delivered_at = CASE WHEN ? = 'delivered' THEN CURRENT_TIMESTAMP ELSE delivered_at END
            """, (order_id, me_order_id, tracking, status, retry_count, error, 
                  me_order_id, tracking, status, retry_count, error, status))
            con.commit()
        logger.debug(f"💾 Pedido {order_id} salvo: status={status}, tracking={tracking}")
    except Exception as e:
        logger.error(f"❌ Erro ao salvar pedido {order_id}: {e}")
        raise

def db_pending() -> List[Tuple[str, str, str]]:
    """Retorna pedidos pendentes de verificação de entrega."""
    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.execute("""
            SELECT bagy_order_id, melhorenvio_order_id, tracking_code FROM orders
            WHERE status IN ('created','shipped') 
            AND tracking_code IS NOT NULL 
            AND tracking_code != 'SEM-RASTREIO'
            AND retry_count < ?
            ORDER BY updated_at ASC
            """, (MAX_RETRIES * 2,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Erro ao buscar pedidos pendentes: {e}")
        return []

def db_stats() -> Dict[str, int]:
    """Retorna estatísticas do banco de dados."""
    try:
        with sqlite3.connect(DB_PATH) as con:
            stats = {}
            cur = con.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
            for status, count in cur.fetchall():
                stats[status] = count
            cur = con.execute("SELECT COUNT(*) FROM orders")
            stats['total'] = cur.fetchone()[0]
            return stats
    except Exception as e:
        logger.error(f"❌ Erro ao obter estatísticas: {e}")
        return {}

# === DECORADOR DE RETRY ===
def retry_on_failure(max_attempts: int = MAX_RETRIES, delay: int = 2):
    """Decorador para tentar novamente em caso de falha."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts:
                        logger.warning(f"⚠️  Tentativa {attempt}/{max_attempts} falhou para {func.__name__}: {e}. Tentando novamente em {delay}s...")
                        time.sleep(delay)
                    else:
                        logger.error(f"❌ Todas as {max_attempts} tentativas falharam para {func.__name__}: {e}")
            raise last_exception
        return wrapper
    return decorator

# === FUNÇÕES BAGY ===
def bagy_headers() -> Dict[str, str]:
    """Retorna headers para requisições à API da Bagy."""
    if not BAGY_TOKEN:
        raise ValueError("BAGY_TOKEN não configurado")
    return {
        "Authorization": f"Bearer {BAGY_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

@retry_on_failure(max_attempts=MAX_RETRIES)
def bagy_mark_shipped(order_id: str, tracking_code: str):
    """Marca pedido como enviado na Bagy."""
    url = f"{BAGY_BASE}/orders/{order_id}/fulfillment/shipped"
    body = {
        "shipping_code": tracking_code,
        "shipping_carrier": "Melhor Envio"
    }
    
    logger.info(f"📤 Marcando pedido {order_id} como enviado na Bagy...")
    r = requests.put(url, headers=bagy_headers(), json=body, timeout=REQUEST_TIMEOUT)
    
    if not r.ok:
        error_msg = f"Erro Bagy shipped [HTTP {r.status_code}]: {r.text}"
        logger.error(f"❌ {error_msg}")
        raise Exception(error_msg)
    
    logger.info(f"✅ Pedido {order_id} marcado como enviado na Bagy")
    return r.json() if r.content else {}

@retry_on_failure(max_attempts=MAX_RETRIES)
def bagy_mark_delivered(order_id: str):
    """Marca pedido como entregue na Bagy."""
    url = f"{BAGY_BASE}/orders/{order_id}/fulfillment/delivered"
    
    logger.info(f"📦 Marcando pedido {order_id} como entregue na Bagy...")
    r = requests.put(url, headers=bagy_headers(), timeout=REQUEST_TIMEOUT)
    
    if not r.ok:
        error_msg = f"Erro Bagy delivered [HTTP {r.status_code}]: {r.text}"
        logger.error(f"❌ {error_msg}")
        raise Exception(error_msg)
    
    logger.info(f"✅ Pedido {order_id} marcado como entregue na Bagy")
    return r.json() if r.content else {}

# === FUNÇÕES MELHOR ENVIO ===
def melhorenvio_headers() -> Dict[str, str]:
    """Retorna headers para requisições à API do Melhor Envio."""
    if not MELHORENVIO_TOKEN:
        raise ValueError("MELHORENVIO_TOKEN não configurado")
    return {
        "Authorization": f"Bearer {MELHORENVIO_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def normalize_order_data(pedido: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza dados do pedido - suporta formato direto e formato com 'event'/'data'."""
    # Se o webhook vier com estrutura {"event": "...", "data": {...}}
    if "event" in pedido and "data" in pedido:
        logger.info(f"📦 Formato webhook com event: {pedido.get('event')}")
        return pedido["data"]
    
    # Formato direto (pedido completo no root)
    return pedido

@retry_on_failure(max_attempts=MAX_RETRIES)
def send_to_melhorenvio(pedido: Dict[str, Any]) -> Tuple[str, str]:
    """Envia pedido para o Melhor Envio e retorna (order_id, tracking_code)."""
    # Normalizar dados do pedido
    pedido = normalize_order_data(pedido)
    
    order_id = pedido.get("id", "UNKNOWN")
    logger.info(f"📋 Extraindo dados do pedido {order_id}...")
    
    # Extrair dados do endereço
    addr = pedido.get("address", {}) or pedido.get("shipping_address", {})
    logger.info(f"📍 Endereço encontrado: {bool(addr)} - Dados: {addr}")
    if not addr:
        raise ValueError("Endereço de entrega não encontrado no pedido")
    
    # Extrair dados do cliente
    cust = pedido.get("customer", {})
    logger.info(f"👤 Cliente encontrado: {bool(cust)} - Nome: {cust.get('name', 'N/A')}")
    if not cust:
        raise ValueError("Dados do cliente não encontrados no pedido")
    
    # Processar itens e calcular dimensões
    items = pedido.get("items", []) or []
    logger.info(f"📦 Itens encontrados: {len(items)}")
    if not items:
        logger.warning(f"⚠️  Pedido {order_id} sem itens, usando valores padrão")
        items = [{"weight": 0.3, "length": 20, "height": 10, "width": 15, "quantity": 1}]
    
    # Calcular peso e dimensões totais
    total_weight = sum(float(it.get("weight", 0.3)) * int(it.get("quantity", 1)) for it in items)
    total_weight = max(total_weight, 0.3)  # Peso mínimo 300g
    logger.info(f"⚖️  Peso total calculado: {total_weight}kg")
    
    # Pegar as maiores dimensões
    max_length = max((float(it.get("length", 20)) for it in items), default=20)
    max_height = max((float(it.get("height", 10)) for it in items), default=10)
    max_width = max((float(it.get("width", 15)) for it in items), default=15)
    logger.info(f"📏 Dimensões: {max_length}x{max_width}x{max_height}cm")
    
    # Calcular valor da nota fiscal
    invoice_value = float(pedido.get("total", 0)) or sum(
        float(it.get("price", 0)) * int(it.get("quantity", 1)) for it in items
    )
    invoice_value = max(invoice_value, 10.0)  # Valor mínimo
    logger.info(f"💰 Valor da nota fiscal: R$ {invoice_value}")
    
    # Validar e limpar CPF do cliente
    customer_doc = clean_document(cust.get("document", ""))
    if customer_doc and not validate_cpf(customer_doc):
        logger.warning(f"⚠️  CPF inválido '{customer_doc}' - será enviado vazio ao Melhor Envio")
        customer_doc = ""
    elif customer_doc:
        logger.info(f"✅ CPF do cliente validado: {customer_doc[:3]}***{customer_doc[-2:]}")
    else:
        logger.warning(f"⚠️  Pedido sem CPF do cliente - será enviado vazio")
    
    # Limpar CEP
    customer_zipcode = clean_zipcode(addr.get("zipcode", ""))
    sender_zipcode = clean_zipcode(SENDER_ZIPCODE)
    
    logger.info(f"📮 CEP origem: {sender_zipcode}, CEP destino: {customer_zipcode}")
    
    # Montar payload do Melhor Envio
    payload = {
        "service": SERVICE_ID,
        "from": {
            "name": SENDER_NAME,
            "phone": SENDER_PHONE,
            "email": SENDER_EMAIL,
            "document": SENDER_DOCUMENT,
            "address": SENDER_ADDRESS,
            "complement": SENDER_COMPLEMENT,
            "number": SENDER_NUMBER,
            "district": SENDER_DISTRICT,
            "city": SENDER_CITY,
            "state_abbr": SENDER_STATE,
            "postal_code": sender_zipcode
        },
        "to": {
            "name": cust.get("name", "Cliente"),
            "phone": cust.get("phone", ""),
            "email": cust.get("email", ""),
            "document": customer_doc,
            "address": addr.get("street", ""),
            "complement": addr.get("complement", ""),
            "number": addr.get("number", "S/N"),
            "district": addr.get("district", addr.get("neighborhood", "")),
            "city": addr.get("city", ""),
            "state_abbr": addr.get("state", ""),
            "postal_code": customer_zipcode
        },
        "products": [{
            "name": f"Pedido #{order_id}",
            "quantity": 1,
            "unitary_value": invoice_value
        }],
        "volumes": [{
            "height": int(max_height),
            "width": int(max_width),
            "length": int(max_length),
            "weight": total_weight
        }],
        "options": {
            "insurance_value": invoice_value,
            "receipt": False,
            "own_hand": False,
            "collect": False
        }
    }
    
    logger.info(f"🚚 Enviando pedido {order_id} para Melhor Envio...")
    logger.info(f"📤 Payload completo do Melhor Envio: {payload}")
    
    # Criar ordem no Melhor Envio
    url = f"{MELHORENVIO_BASE}/me/cart"
    logger.info(f"🔗 URL da API: {url}")
    
    r = requests.post(url, headers=melhorenvio_headers(), json=payload, timeout=REQUEST_TIMEOUT)
    logger.info(f"📥 Resposta da API Melhor Envio: Status={r.status_code}, Body={r.text[:500]}")
    
    if not r.ok:
        error_msg = f"Erro Melhor Envio [HTTP {r.status_code}]: {r.text}"
        logger.error(f"❌ {error_msg}")
        raise Exception(error_msg)
    
    data = r.json() if r.content else {}
    logger.debug(f"Resposta Melhor Envio: {data}")
    
    # Extrair ID da ordem e código de rastreio
    me_order_id = data.get("id", "")
    tracking = data.get("tracking", "") or data.get("protocol", "") or "SEM-RASTREIO"
    
    if not me_order_id:
        logger.warning(f"⚠️  Melhor Envio não retornou ID da ordem para pedido {order_id}")
    
    logger.info(f"✅ Pedido {order_id} enviado ao Melhor Envio. ME ID: {me_order_id}, Rastreio: {tracking}")
    return (me_order_id, tracking)

def melhorenvio_check_delivered(me_order_id: str) -> bool:
    """Verifica se pedido foi entregue consultando status no Melhor Envio."""
    try:
        url = f"{MELHORENVIO_BASE}/me/shipment/tracking"
        payload = {"orders": [me_order_id]}
        
        logger.debug(f"🔍 Consultando status do pedido {me_order_id} no Melhor Envio...")
        
        r = requests.post(url, headers=melhorenvio_headers(), json=payload, timeout=REQUEST_TIMEOUT)
        
        if not r.ok:
            logger.warning(f"⚠️  Erro ao consultar pedido {me_order_id} [HTTP {r.status_code}]: {r.text}")
            return False
        
        data = r.json() if r.content else {}
        
        # O Melhor Envio pode retornar array de pedidos
        orders = data if isinstance(data, list) else [data]
        
        for order_data in orders:
            status = str(order_data.get("status", "")).lower()
            
            is_delivered = (
                "entregue" in status or 
                "delivered" in status or 
                "finalizado" in status or
                status == "delivered"
            )
            
            if is_delivered:
                logger.info(f"📦 Pedido {me_order_id} está ENTREGUE (status: {status})")
                return True
            else:
                logger.debug(f"Pedido {me_order_id} ainda não entregue (status: {status})")
        
        return False
    except Exception as e:
        logger.error(f"❌ Erro ao verificar pedido {me_order_id}: {e}")
        return False

# === WEBHOOK ===
@app.route("/webhook", methods=["POST", "GET"])
@app.route("/", methods=["POST", "GET"])
@app.route("/order", methods=["POST", "GET"])
def webhook():
    """Endpoint para receber webhooks da Bagy (aceita /, /webhook, /order - GET e POST)."""
    try:
        # Suportar GET (estilo integração nativa) e POST
        if request.method == "GET":
            order_id = request.args.get("order") or request.args.get("id")
            logger.info(f"📥 Webhook GET recebido - order_id: {order_id}, query params: {dict(request.args)}")
            
            if not order_id:
                logger.warning("⚠️  Webhook GET sem parâmetro 'order' ou 'id'")
                return jsonify({"error": "Parâmetro 'order' não encontrado"}), 400
            
            # Buscar pedido completo da API Bagy
            try:
                logger.info(f"🔍 Buscando dados do pedido {order_id} na Bagy...")
                pedido = bagy_get_order(order_id)
                logger.info(f"📦 Pedido obtido da Bagy: {pedido}")
            except Exception as e:
                logger.error(f"❌ Erro ao buscar pedido da Bagy: {e}")
                return jsonify({"error": f"Erro ao buscar pedido: {str(e)}"}), 500
        else:
            # POST - pedido vem no body
            pedido = request.json or {}
        
        return webhook_handler(pedido)
    except Exception as e:
        logger.error(f"❌ Erro no webhook: {e}")
        return jsonify({"error": str(e)}), 500

# === MONITOR DE RASTREIO ===
def tracking_worker():
    """Worker que monitora status de entrega dos pedidos."""
    logger.info(f"🔄 Iniciando monitor de rastreio (intervalo: {TRACKER_INTERVAL}s)")
    
    while True:
        try:
            pending_orders = db_pending()
            
            if pending_orders:
                logger.info(f"🔍 Verificando {len(pending_orders)} pedidos pendentes...")
            
            for bagy_order_id, me_order_id, tracking_code in pending_orders:
                try:
                    if me_order_id and melhorenvio_check_delivered(me_order_id):
                        bagy_mark_delivered(bagy_order_id)
                        db_save(bagy_order_id, me_order_id, tracking_code, status="delivered")
                        logger.info(f"✅ Pedido {bagy_order_id} marcado como entregue! (ME ID: {me_order_id})")
                    else:
                        logger.debug(f"Pedido {bagy_order_id} ainda não entregue (ME ID: {me_order_id})")
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"❌ Erro ao verificar pedido {bagy_order_id}: {error_msg}")
                    db_save(bagy_order_id, me_order_id, tracking_code, error=error_msg)
                
                time.sleep(2)
        
        except Exception as e:
            logger.error(f"❌ Erro no worker de rastreio: {e}")
        
        logger.debug(f"💤 Aguardando {TRACKER_INTERVAL}s para próxima verificação...")
        time.sleep(TRACKER_INTERVAL)

# === ENDPOINTS DE STATUS ===
@app.route("/", methods=["GET"])
def status():
    """Endpoint de health check básico."""
    return jsonify({
        "status": "online",
        "service": "Webhook Bagy-MelhorEnvio",
        "message": "🚀 Serviço ativo e monitorando pedidos",
        "version": "1.0"
    }), 200

@app.route("/health", methods=["GET"])
def health():
    """Endpoint de health check detalhado."""
    try:
        stats = db_stats()
        config_ok = bool(BAGY_TOKEN and MELHORENVIO_TOKEN)
        
        return jsonify({
            "status": "healthy" if config_ok else "degraded",
            "timestamp": datetime.datetime.now().isoformat(),
            "configuration": {
                "bagy_token_configured": bool(BAGY_TOKEN),
                "melhorenvio_token_configured": bool(MELHORENVIO_TOKEN),
                "sender_zipcode": SENDER_ZIPCODE,
                "service_id": SERVICE_ID,
                "tracker_interval": TRACKER_INTERVAL
            },
            "database": {
                "path": DB_PATH,
                "stats": stats
            }
        }), 200
    except Exception as e:
        logger.error(f"❌ Erro no health check: {e}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500

@app.route("/stats", methods=["GET"])
def stats_endpoint():
    """Endpoint para visualizar estatísticas."""
    try:
        stats = db_stats()
        return jsonify({
            "statistics": stats,
            "timestamp": datetime.datetime.now().isoformat()
        }), 200
    except Exception as e:
        logger.error(f"❌ Erro ao obter estatísticas: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/test-webhook", methods=["POST"])
def test_webhook():
    """Endpoint de teste para simular webhooks da Bagy."""
    # Payload de exemplo da Bagy
    test_payload = {
        "id": "TEST-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"),
        "fulfillment_status": "invoiced",
        "total": 150.00,
        "customer": {
            "name": "Cliente Teste",
            "email": "teste@example.com",
            "phone": "11999999999",
            "document": "12345678909"  # CPF válido para teste
        },
        "address": {
            "street": "Avenida Paulista",
            "number": "1000",
            "complement": "Apto 45",
            "district": "Bela Vista",
            "city": "São Paulo",
            "state": "SP",
            "zipcode": "01310-100"
        },
        "items": [{
            "name": "Produto Teste",
            "quantity": 1,
            "price": 150.00,
            "weight": 0.5,
            "length": 20,
            "width": 15,
            "height": 10
        }]
    }
    
    logger.info("🧪 Recebendo teste de webhook...")
    
    # Processar como webhook normal
    return webhook_handler(test_payload)

def webhook_handler(pedido: Dict[str, Any]):
    """Handler reutilizável para processar webhooks."""
    try:
        logger.info(f"📥 Webhook recebido! Payload completo: {pedido}")
        
        # Normalizar dados do pedido (extrair de "data" se necessário)
        pedido_normalizado = normalize_order_data(pedido)
        order_id = pedido_normalizado.get("id")
        order_code = pedido_normalizado.get("code")
        
        if not order_id:
            logger.warning("⚠️  Webhook recebido sem ID de pedido")
            return jsonify({"error": "ID do pedido não encontrado"}), 400
        
        logger.info(f"📥 Processando pedido #{order_code} (ID: {order_id})")
        
        # Verificar fulfillment_status - SÓ PROCESSAR SE ESTIVER FATURADO
        fulfillment_status = pedido_normalizado.get("fulfillment_status", "")
        logger.info(f"📊 Status do fulfillment: '{fulfillment_status}'")
        
        if fulfillment_status != "invoiced":
            logger.info(f"⏭️  Pedido #{order_code} (ID: {order_id}) ignorado - status '{fulfillment_status}' (esperado: 'invoiced')")
            return jsonify({
                "message": "Pedido ignorado - apenas pedidos FATURADOS são processados",
                "order_id": order_id,
                "order_code": order_code,
                "fulfillment_status": fulfillment_status,
                "required": "invoiced"
            }), 200
        
        logger.info(f"✅ Pedido #{order_code} (ID: {order_id}) está FATURADO, processando...")
        
        # Verificar se já foi processado
        with sqlite3.connect(DB_PATH) as con:
            cur = con.execute("SELECT status FROM orders WHERE bagy_order_id = ?", (order_id,))
            existing = cur.fetchone()
            if existing and existing[0] in ['shipped', 'delivered']:
                logger.info(f"⏭️  Pedido {order_id} já foi processado (status: {existing[0]})")
                return jsonify({
                    "message": "Pedido já processado",
                    "status": existing[0]
                }), 200
        
        # Processar pedido
        try:
            logger.info(f"🚀 Iniciando envio para Melhor Envio...")
            me_order_id, tracking = send_to_melhorenvio(pedido_normalizado)
            logger.info(f"✅ Melhor Envio respondeu: ID={me_order_id}, Tracking={tracking}")
            
            logger.info(f"📦 Marcando pedido como enviado na Bagy...")
            bagy_mark_shipped(order_id, tracking)
            logger.info(f"✅ Pedido marcado como enviado na Bagy")
            
            db_save(order_id, me_order_id, tracking, status="shipped")
            
            logger.info(f"✅ Pedido {order_id} processado com sucesso! ME ID: {me_order_id}, Rastreio: {tracking}")
            return jsonify({
                "success": True,
                "order_id": order_id,
                "melhorenvio_order_id": me_order_id,
                "tracking_code": tracking,
                "message": "Pedido enviado ao Melhor Envio e marcado como enviado na Bagy"
            }), 200
            
        except Exception as e:
            import traceback
            error_msg = str(e)
            stack_trace = traceback.format_exc()
            logger.error(f"❌ Erro ao processar pedido {order_id}: {error_msg}")
            logger.error(f"Stack trace completo:\n{stack_trace}")
            db_save(order_id, status="error", error=error_msg)
            
            return jsonify({
                "error": error_msg,
                "order_id": order_id,
                "details": stack_trace
            }), 500
    
    except Exception as e:
        import traceback
        error_msg = str(e)
        stack_trace = traceback.format_exc()
        logger.error(f"❌ Erro crítico no webhook: {error_msg}")
        logger.error(f"Stack trace:\n{stack_trace}")
        return jsonify({
            "error": "Erro interno ao processar webhook",
            "details": error_msg,
            "stack_trace": stack_trace
        }), 500

if __name__ == "__main__":
    logger.info("="*60)
    logger.info("🚀 INICIANDO WEBHOOK BAGY-MELHORENVIO")
    logger.info("="*60)
    logger.info(f"📍 Remetente: {SENDER_NAME}")
    logger.info(f"📮 CEP: {SENDER_ZIPCODE}")
    logger.info(f"🚚 Serviço: {SERVICE_ID} (1=PAC, 2=SEDEX, 3=PAC Mini)")
    logger.info(f"⏱️  Intervalo de rastreio: {TRACKER_INTERVAL}s")
    logger.info(f"🔄 Tentativas máximas: {MAX_RETRIES}")
    logger.info(f"💾 Banco de dados: {DB_PATH}")
    logger.info("="*60)
    
    # Iniciar worker de rastreio
    tracking_thread = threading.Thread(target=tracking_worker, daemon=True, name="TrackingWorker")
    tracking_thread.start()
    logger.info("✅ Worker de rastreio iniciado")
    
    # Iniciar servidor Flask
    port = int(os.getenv("PORT", 3000))
    logger.info(f"🌐 Servidor Flask iniciando na porta {port}...")
    logger.info("="*60)
    
    app.run(host="0.0.0.0", port=port, debug=False)
