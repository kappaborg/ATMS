FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ /app/src/

EXPOSE 8501

# Operator console reads /tmp/atms-demo-state.json by default; in the
# docker-compose-demo stack, the simulation orchestrator and the console
# share /tmp via a named volume (see docker-compose.demo.yml).
CMD ["streamlit", "run", "src/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
