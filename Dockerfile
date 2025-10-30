FROM python:3.11-slim

# Define diretório de trabalho
WORKDIR /app

# Instala dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia arquivos de dependências
COPY requirements.txt .

# Instala dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia código da aplicação
COPY main.py .

# Cria diretório para banco de dados
RUN mkdir -p /app/data

# Expõe porta
EXPOSE 3000

# Define variáveis de ambiente padrão
ENV PORT=3000
ENV DB_PATH=/app/data/data.db

# Comando de inicialização
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:3000", "--workers", "2", "--threads", "4", "--timeout", "120", "--log-level", "info"]
