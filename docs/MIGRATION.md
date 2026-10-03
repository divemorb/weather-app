# Upgrading from v1 to v2

v2 replaces the Python backend with a Rust one. It keeps the API (with a few added fields), the database, the port and the data volume, so the accuracy history carries over. The page is new.

| | v1.0 (Python) | v2.0 (Rust) |
|---|---|---|
| Image | about 200 MB | about 12 MB |
| Memory while running | about 60 MB | about 10 MB |
| Page | single page | rain answer first, details on demand, kiosk view (`/?kiosk`), English and German |
| API | | adds the weather stations behind the data (`/api/now`, `/api/model-accuracy`) |

## 1. Back up

Stop the app and copy the database out of its volume. The volume is named after your clone's folder (`docker volume ls | grep weather-data`), for example `weather-app_weather-data`:

```bash
docker compose down
docker run --rm -v weather-app_weather-data:/data -v "$PWD":/backup busybox cp /data/weather.db /backup/weather-v1.db
```

## 2. Upgrade

```bash
git fetch --tags
git checkout v2.0
docker compose up -d --build
```

## 3. Check

The location and the accuracy history are still there:

```bash
curl -s localhost:8000/api/config | grep -o '"location":[^}]*}'
curl -s localhost:8000/api/model-accuracy | grep -o '"n_samples":[0-9]*' | sort -u
```

## Roll back

```bash
docker compose down
git checkout v1.0
docker compose up -d --build
```

v1 reads the database as v2 left it (same schema; v2's extra `observation_stations` entry is ignored). To return to the exact state before the upgrade, restore the backup before `docker compose up`:

```bash
docker run --rm -v weather-app_weather-data:/data -v "$PWD":/backup busybox cp /backup/weather-v1.db /data/weather.db
```

With Podman, use `podman compose` and `podman run` the same way.
