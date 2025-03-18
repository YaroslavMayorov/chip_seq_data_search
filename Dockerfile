FROM python:3.11
WORKDIR /app
COPY . /app
RUN apt-get update && apt-get install -y bedtools
RUN pip install -r requirements.txt
CMD ["python", "app/main.py"]
