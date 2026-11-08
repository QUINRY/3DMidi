FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/3dmidi
COPY requirements.txt ./requirements.txt
COPY deploy/requirements.txt ./deploy/requirements.txt
RUN pip install --no-cache-dir -r deploy/requirements.txt
COPY app ./app
COPY tools ./tools
COPY reference/ke-startup/midi_ke_slow_z.cfg reference/ke-startup/KE_YAVAS_Z_KURULUM.txt ./reference/ke-startup/
USER 10001:10001
WORKDIR /srv/3dmidi/app
EXPOSE 8765
CMD ["waitress-serve", "--listen=0.0.0.0:8765", "--threads=4", "--connection-limit=48", "--backlog=32", "--channel-timeout=30", "--max-request-header-size=32768", "--max-request-body-size=4259840", "--call", "web:create_app"]
