FROM python:3.12-slim

RUN python -m pip install --upgrade pip

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install -r requirements.txt --upgrade

COPY . .

CMD ["python", "bot.py"]