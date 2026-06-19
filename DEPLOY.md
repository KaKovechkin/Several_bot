# Деплой Sevrax

## Подготовка

1. Получи токен у [@BotFather](https://t.me/BotFather).
2. Скопируй `.env.example` → `.env` и впиши `TG_TOKEN`.
3. **Секреты только в `.env`** — он в `.gitignore`, в репозиторий не попадает.

## Вариант A — Docker (рекомендуется)

```bash
docker compose up -d --build      # сборка и запуск в фоне
docker compose logs -f            # логи
docker compose down               # остановка
```

- `restart: always` — автозапуск при перезагрузке сервера и при падении.
- БД хранится в `./data/messages.db` (volume), переживает пересборку.
- Healthcheck проверяет что процесс `run.py` жив.

## Вариант B — systemd (без Docker)

```bash
sudo useradd -r -s /usr/sbin/nologin dialogspy
sudo mkdir -p /opt/dialogspy && sudo chown dialogspy /opt/dialogspy
# скопировать код в /opt/dialogspy, создать venv и установить зависимости:
python3.11 -m venv /opt/dialogspy/.venv
/opt/dialogspy/.venv/bin/pip install -r /opt/dialogspy/requirements.txt

sudo cp deploy/dialogspy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dialogspy      # автозапуск + старт
sudo systemctl status dialogspy
journalctl -u dialogspy -f                  # логи
```

`Restart=always` поднимает бота заново при падении.

## Хостинг (VPS)

Подойдёт любой дешёвый VPS — бот лёгкий:
- **Hetzner** Cloud CX22 (~€4/мес) — лучшее соотношение цена/мощность.
- **DigitalOcean** Basic Droplet ($4–6/мес) — простой UI.
- **TimeWeb Cloud** — удобно при оплате из РФ.

1 vCPU / 1–2 GB RAM достаточно.

## Мониторинг падений

- Docker `restart: always` / systemd `Restart=always` поднимают процесс автоматически.
- Логирование идёт в stdout (`docker logs` / `journalctl`).
- Чтобы получать **уведомление владельцу если бот упал**, добавь внешнюю
  проверку (бот не может сообщить о собственном падении изнутри):
  - простой cron-скрипт на сервере, который пингует процесс и шлёт сообщение
    через Bot API при отсутствии;
  - либо аптайм-монитор (UptimeRobot / Healthchecks.io): бот периодически
    дёргает heartbeat-URL, монитор алертит при пропаже.
