FROM python:3.12-slim

WORKDIR /code

# Dependências primeiro: a camada fica em cache enquanto requirements.txt não mudar.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# --reload: o docker-compose monta ./api em /code, então editar o código
# reinicia a API sem rebuild (útil durante as fases do trabalho).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
