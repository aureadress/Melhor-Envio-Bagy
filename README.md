# 🚀 Integração Bagy → Melhor Envio

Webhook Flask robusto e otimizado para automatizar o envio de pedidos faturados da **Bagy** para o **Melhor Envio** com monitoramento automático de entrega.

## ✨ Funcionalidades

- ✅ **Recebe webhooks** da Bagy quando pedidos são faturados
- ✅ **Cria envios automaticamente** no Melhor Envio
- ✅ **Atualiza status** na Bagy (enviado → entregue)
- ✅ **Monitor automático** verifica entregas periodicamente
- ✅ **Retry inteligente** em caso de falhas
- ✅ **Logs detalhados** com emojis para fácil visualização
- ✅ **Health checks** e estatísticas em tempo real
- ✅ **Banco SQLite** para persistência e controle
- ✅ **100% pronto para produção**

## 📋 Requisitos

- Python 3.11+
- Conta ativa no Melhor Envio
- Tokens de API:
  - `BAGY_TOKEN` - Token de autenticação da Bagy
  - `MELHORENVIO_TOKEN` - Token de autenticação do Melhor Envio

## 🔧 Instalação Local

### 1. Clone o repositório

```bash
git clone https://github.com/aureadress/Bagy-MelhorEnvio.git
cd Bagy-MelhorEnvio
```

### 2. Crie ambiente virtual

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows
```

### 3. Instale dependências

```bash
pip install -r requirements.txt
```

### 4. Configure variáveis de ambiente

```bash
cp .env.example .env
# Edite .env e adicione seus tokens e dados do remetente
```

### 5. Execute a aplicação

```bash
python main.py
```

A aplicação estará rodando em `http://localhost:3000`

## ⚙️ Variáveis de Ambiente

### Obrigatórias

| Variável | Descrição |
|----------|-----------|
| `BAGY_TOKEN` | Token de autenticação da API Bagy |
| `MELHORENVIO_TOKEN` | Token de autenticação da API Melhor Envio |
| `SENDER_NAME` | Nome do remetente |
| `SENDER_PHONE` | Telefone do remetente |
| `SENDER_EMAIL` | Email do remetente |
| `SENDER_DOCUMENT` | CPF/CNPJ do remetente |
| `SENDER_ADDRESS` | Endereço do remetente |
| `SENDER_NUMBER` | Número do endereço |
| `SENDER_DISTRICT` | Bairro do remetente |
| `SENDER_CITY` | Cidade do remetente |
| `SENDER_STATE` | Estado do remetente (UF) |
| `SENDER_ZIPCODE` | CEP do remetente |

### Opcionais

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `SERVICE_ID` | `1` | ID do serviço (1=PAC, 2=SEDEX, 3=PAC Mini) |
| `TRACKER_INTERVAL` | `600` | Intervalo de verificação de rastreio (segundos) |
| `MAX_RETRIES` | `3` | Número máximo de tentativas em caso de erro |
| `REQUEST_TIMEOUT` | `30` | Timeout de requisições HTTP (segundos) |
| `PORT` | `3000` | Porta do servidor |

## 🐳 Deploy com Docker

### Usando Docker Compose (Recomendado)

```bash
# Configure as variáveis no .env
cp .env.example .env
nano .env  # Edite com seus dados

# Inicie o serviço
docker-compose up -d

# Verifique os logs
docker-compose logs -f

# Pare o serviço
docker-compose down
```

## ☁️ Deploy em Nuvem

### Railway.app (Recomendado)

1. Faça push para GitHub
2. Acesse [Railway.app](https://railway.app)
3. Clique em **"New Project" → "Deploy from GitHub"**
4. Selecione: **aureadress/Bagy-MelhorEnvio**
5. Adicione **TODAS** as variáveis de ambiente (tokens + dados do remetente)
6. Aguarde o deploy
7. Copie a URL gerada

### Render.com

1. Acesse [Render.com](https://render.com)
2. Clique em **"New +" → "Web Service"**
3. Conecte: **aureadress/Bagy-MelhorEnvio**
4. Configure:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn main:app --bind 0.0.0.0:$PORT`
5. Adicione as variáveis de ambiente
6. Clique em **"Create Web Service"**

## 🔗 Configurar Webhook na Bagy

Após fazer o deploy:

1. Acesse **Bagy → Configurações → Integrações → Webhooks**
2. Clique em **"Adicionar Webhook"**
3. Configure:
   - **Evento:** Pedido Faturado
   - **URL:** `https://sua-url.com/webhook`
   - **Método:** POST
4. Salve

## 📊 Endpoints da API

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/` | GET | Health check básico |
| `/health` | GET | Status detalhado do sistema |
| `/stats` | GET | Estatísticas de pedidos |
| `/webhook` | POST | Recebe webhooks da Bagy |

### Exemplo de Resposta `/health`

```json
{
  "status": "healthy",
  "timestamp": "2025-10-30T10:30:00",
  "configuration": {
    "bagy_token_configured": true,
    "melhorenvio_token_configured": true,
    "sender_zipcode": "03320-001",
    "service_id": 1,
    "tracker_interval": 600
  },
  "database": {
    "path": "data.db",
    "stats": {
      "created": 5,
      "shipped": 12,
      "delivered": 8,
      "total": 25
    }
  }
}
```

## 🧪 Testes

### Teste Manual

```bash
curl -X POST https://sua-url.com/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "id": "TEST-123",
    "fulfillment_status": "invoiced",
    "customer": {
      "name": "Cliente Teste",
      "email": "teste@email.com",
      "phone": "11999999999",
      "document": "12345678901"
    },
    "address": {
      "zipcode": "01310-100",
      "street": "Av. Paulista",
      "number": "1000",
      "district": "Bela Vista",
      "city": "São Paulo",
      "state": "SP"
    },
    "items": [{
      "weight": 0.5,
      "length": 20,
      "height": 10,
      "width": 15,
      "quantity": 1,
      "price": 50.00
    }],
    "total": 50.00
  }'
```

## 🔒 Segurança

- ✅ Tokens armazenados em variáveis de ambiente
- ✅ Validação de entrada em todos os endpoints
- ✅ Timeout em requisições HTTP
- ✅ Retry automático com limite
- ✅ Logs sem informações sensíveis
- ✅ HTTPS obrigatório (via plataforma de deploy)

## 🆘 Troubleshooting

### Erro: "MELHORENVIO_TOKEN não configurado"
**Solução:** Configure a variável `MELHORENVIO_TOKEN` com o token do Melhor Envio.

### Erro: "HTTP 401" do Melhor Envio
**Solução:** Token incorreto ou expirado. Gere um novo token no painel do Melhor Envio.

### Webhook não está sendo recebido
**Soluções:**
1. Verifique se a URL está correta na Bagy
2. Teste manualmente com `curl`
3. Verifique os logs do servidor
4. Confirme que a aplicação está rodando (`/health`)

### Pedidos não são marcados como entregues
**Soluções:**
1. Verifique os logs para erros na consulta ao Melhor Envio
2. Confirme que `TRACKER_INTERVAL` não está muito alto
3. Verifique se o pedido tem ID do Melhor Envio no banco

## 📝 Como Obter Token do Melhor Envio

1. Acesse: https://melhorenvio.com.br
2. Faça login
3. Vá em **Configurações → API → Tokens**
4. Clique em **"Gerar Token"**
5. Copie o token gerado

⚠️ **IMPORTANTE:** O token do Melhor Envio tem formato:
```
Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

Configure no Railway **COM** o "Bearer" na frente!

## 📈 Performance

- **Retry automático:** Até 3 tentativas em caso de falha
- **Worker assíncrono:** Monitoramento em thread separada
- **Banco indexado:** Queries otimizadas
- **Timeout configurável:** Evita travamentos
- **Logs eficientes:** Debug opcional

## 🤝 Contribuindo

Contribuições são bem-vindas! Para contribuir:

1. Fork o projeto
2. Crie uma branch: `git checkout -b feature/nova-funcionalidade`
3. Commit: `git commit -m 'Adiciona nova funcionalidade'`
4. Push: `git push origin feature/nova-funcionalidade`
5. Abra um Pull Request

## 📝 Licença

Este projeto é de código aberto e está disponível sob a licença MIT.

## 💡 Suporte

- 📧 Issues: https://github.com/aureadress/Bagy-MelhorEnvio/issues
- 📚 Documentação: README.md

---

**Desenvolvido com ❤️ para automatizar integrações Bagy-Melhor Envio**
