FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY coach ./coach
ENV DB_PATH=/data/coach.db
CMD ["python", "-m", "coach.main"]
