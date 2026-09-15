FROM python:3.13-slim
WORKDIR /app
RUN mkdir /data && chown 10001:10001 /data
COPY notifier.py /app/notifier.py
COPY pop_notifier.py /app/pop_notifier.py
USER 10001:10001
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENV NTU_STATE_DIR=/data
CMD ["python", "notifier.py"]
