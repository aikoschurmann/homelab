"""Apps that can be installed into a machine with one click: a Compose file each.

In a template, {port} is the web port chosen on install, {secret} a fresh random string
(passwords between the app's own containers) and {tz} this server's time zone. Data lives in
named volumes, so the dashboard VM's nightly backup picks it up.
"""

APPS = [
    {"id": "immich", "name": "Immich", "category": "Photos", "port": 2283, "icon": "image",
     "desc": "Photo and video backup from your phone, with faces, places and search.",
     "compose": """name: immich
services:
  immich-server:
    container_name: immich_server
    image: ghcr.io/immich-app/immich-server:release
    volumes:
      - immich_upload:/data
      - /etc/localtime:/etc/localtime:ro
    environment:
      DB_PASSWORD: "{secret}"
      DB_USERNAME: postgres
      DB_DATABASE_NAME: immich
    ports:
      - "{port}:2283"
    depends_on: [redis, database]
    restart: always
  immich-machine-learning:
    container_name: immich_machine_learning
    image: ghcr.io/immich-app/immich-machine-learning:release
    volumes:
      - immich_model_cache:/cache
    restart: always
  redis:
    container_name: immich_redis
    image: docker.io/valkey/valkey:8-bookworm
    restart: always
  database:
    container_name: immich_postgres
    image: ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0
    environment:
      POSTGRES_PASSWORD: "{secret}"
      POSTGRES_USER: postgres
      POSTGRES_DB: immich
      POSTGRES_INITDB_ARGS: "--data-checksums"
    volumes:
      - immich_db:/var/lib/postgresql/data
    shm_size: 128mb
    restart: always
volumes:
  immich_upload: {{ name: immich_upload }}
  immich_model_cache: {{ name: immich_model_cache }}
  immich_db: {{ name: immich_db }}
"""},
    {"id": "vaultwarden", "name": "Vaultwarden", "category": "Security", "port": 8222, "icon": "key-round",
     "desc": "A password manager server that works with the Bitwarden apps.",
     "compose": """name: vaultwarden
services:
  vaultwarden:
    container_name: vaultwarden
    image: vaultwarden/server:latest
    environment:
      SIGNUPS_ALLOWED: "true"
    volumes:
      - vaultwarden_data:/data
    ports:
      - "{port}:80"
    restart: always
volumes:
  vaultwarden_data: {{ name: vaultwarden_data }}
"""},
    {"id": "home-assistant", "name": "Home Assistant", "category": "Home", "port": 8123, "icon": "house",
     "desc": "Home automation: lights, sensors and everything smart in the house, in one place.",
     "compose": """name: home-assistant
services:
  homeassistant:
    container_name: homeassistant
    image: ghcr.io/home-assistant/home-assistant:stable
    environment:
      TZ: "{tz}"
    volumes:
      - homeassistant_config:/config
    ports:
      - "{port}:8123"
    restart: always
volumes:
  homeassistant_config: {{ name: homeassistant_config }}
"""},
    {"id": "uptime-kuma", "name": "Uptime Kuma", "category": "Monitoring", "port": 3001, "icon": "activity",
     "desc": "Status pages and uptime monitoring with many notification types.",
     "compose": """name: uptime-kuma
services:
  uptime-kuma:
    container_name: uptime-kuma
    image: louislam/uptime-kuma:1
    volumes:
      - uptime_kuma_data:/app/data
    ports:
      - "{port}:3001"
    restart: always
volumes:
  uptime_kuma_data: {{ name: uptime_kuma_data }}
"""},
    {"id": "paperless", "name": "Paperless-ngx", "category": "Documents", "port": 8010, "icon": "file-text",
     "desc": "Scan, index and search your paper documents.",
     "compose": """name: paperless
services:
  broker:
    container_name: paperless_redis
    image: docker.io/library/redis:7
    volumes:
      - paperless_redis:/data
    restart: always
  webserver:
    container_name: paperless
    image: ghcr.io/paperless-ngx/paperless-ngx:latest
    depends_on: [broker]
    environment:
      PAPERLESS_REDIS: redis://broker:6379
      PAPERLESS_SECRET_KEY: "{secret}"
      PAPERLESS_TIME_ZONE: "{tz}"
      PAPERLESS_URL: ""
    volumes:
      - paperless_data:/usr/src/paperless/data
      - paperless_media:/usr/src/paperless/media
      - paperless_consume:/usr/src/paperless/consume
    ports:
      - "{port}:8000"
    restart: always
volumes:
  paperless_redis: {{ name: paperless_redis }}
  paperless_data: {{ name: paperless_data }}
  paperless_media: {{ name: paperless_media }}
  paperless_consume: {{ name: paperless_consume }}
"""},
    {"id": "nextcloud", "name": "Nextcloud", "category": "Files", "port": 8081, "icon": "cloud",
     "desc": "Files, calendar and contacts you host yourself.",
     "compose": """name: nextcloud
services:
  nextcloud:
    container_name: nextcloud
    image: nextcloud:apache
    volumes:
      - nextcloud_data:/var/www/html
    ports:
      - "{port}:80"
    restart: always
volumes:
  nextcloud_data: {{ name: nextcloud_data }}
"""},
    {"id": "syncthing", "name": "Syncthing", "category": "Files", "port": 8384, "icon": "refresh-cw",
     "desc": "Keeps folders in sync between your computers, without a cloud.",
     "compose": """name: syncthing
services:
  syncthing:
    container_name: syncthing
    image: syncthing/syncthing:latest
    volumes:
      - syncthing_data:/var/syncthing
    ports:
      - "{port}:8384"
      - "22000:22000/tcp"
      - "22000:22000/udp"
      - "21027:21027/udp"
    restart: always
volumes:
  syncthing_data: {{ name: syncthing_data }}
"""},
    {"id": "forgejo", "name": "Forgejo", "category": "Development", "port": 3000, "icon": "git-branch",
     "desc": "Git hosting with issues and pull requests, like a small GitHub.",
     "compose": """name: forgejo
services:
  forgejo:
    container_name: forgejo
    image: codeberg.org/forgejo/forgejo:11
    environment:
      USER_UID: "1000"
      USER_GID: "1000"
    volumes:
      - forgejo_data:/data
    ports:
      - "{port}:3000"
      - "2222:22"
    restart: always
volumes:
  forgejo_data: {{ name: forgejo_data }}
"""},
    {"id": "navidrome", "name": "Navidrome", "category": "Media", "port": 4533, "icon": "music",
     "desc": "Stream your music collection to any Subsonic app or the browser.",
     "compose": """name: navidrome
services:
  navidrome:
    container_name: navidrome
    image: deluan/navidrome:latest
    volumes:
      - navidrome_data:/data
      - navidrome_music:/music:ro
    ports:
      - "{port}:4533"
    restart: always
volumes:
  navidrome_data: {{ name: navidrome_data }}
  navidrome_music: {{ name: navidrome_music }}
"""},
    {"id": "audiobookshelf", "name": "Audiobookshelf", "category": "Media", "port": 13378, "icon": "headphones",
     "desc": "Audiobooks and podcasts, with progress synced across devices.",
     "compose": """name: audiobookshelf
services:
  audiobookshelf:
    container_name: audiobookshelf
    image: ghcr.io/advplyr/audiobookshelf:latest
    volumes:
      - abs_config:/config
      - abs_metadata:/metadata
      - abs_audiobooks:/audiobooks
      - abs_podcasts:/podcasts
    ports:
      - "{port}:80"
    restart: always
volumes:
  abs_config: {{ name: abs_config }}
  abs_metadata: {{ name: abs_metadata }}
  abs_audiobooks: {{ name: abs_audiobooks }}
  abs_podcasts: {{ name: abs_podcasts }}
"""},
    {"id": "mealie", "name": "Mealie", "category": "Home", "port": 9925, "icon": "chef-hat",
     "desc": "Recipes, meal plans and shopping lists.",
     "compose": """name: mealie
services:
  mealie:
    container_name: mealie
    image: ghcr.io/mealie-recipes/mealie:latest
    environment:
      TZ: "{tz}"
      ALLOW_SIGNUP: "false"
    volumes:
      - mealie_data:/app/data
    ports:
      - "{port}:9000"
    restart: always
volumes:
  mealie_data: {{ name: mealie_data }}
"""},
    {"id": "freshrss", "name": "FreshRSS", "category": "Reading", "port": 8082, "icon": "rss",
     "desc": "A feed reader for blogs and news sites.",
     "compose": """name: freshrss
services:
  freshrss:
    container_name: freshrss
    image: freshrss/freshrss:latest
    environment:
      TZ: "{tz}"
      CRON_MIN: "*/20"
    volumes:
      - freshrss_data:/var/www/FreshRSS/data
      - freshrss_extensions:/var/www/FreshRSS/extensions
    ports:
      - "{port}:80"
    restart: always
volumes:
  freshrss_data: {{ name: freshrss_data }}
  freshrss_extensions: {{ name: freshrss_extensions }}
"""},
    {"id": "stirling-pdf", "name": "Stirling-PDF", "category": "Documents", "port": 8083, "icon": "file-stack",
     "desc": "Merge, split, convert and sign PDFs in the browser.",
     "compose": """name: stirling-pdf
services:
  stirling-pdf:
    container_name: stirling-pdf
    image: stirlingtools/stirling-pdf:latest
    volumes:
      - stirling_configs:/configs
    ports:
      - "{port}:8080"
    restart: always
volumes:
  stirling_configs: {{ name: stirling_configs }}
"""},
    {"id": "it-tools", "name": "IT Tools", "category": "Development", "port": 8084, "icon": "wrench",
     "desc": "Handy converters and generators for developers: JSON, JWT, hashes, UUIDs and more.",
     "compose": """name: it-tools
services:
  it-tools:
    container_name: it-tools
    image: corentinth/it-tools:latest
    ports:
      - "{port}:80"
    restart: always
"""},
]

BY_ID = {a['id']: a for a in APPS}
