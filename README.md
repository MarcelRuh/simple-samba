# Simple Samba UI

Interne Web-Verwaltung für Samba-Freigaben auf Debian – klein, ohne Reverse Proxy, ohne nginx/Caddy/Apache.

## Features

- SMB-Freigaben anlegen, bearbeiten, aktivieren/deaktivieren
- Samba-Benutzer verwalten (`smbpasswd`)
- Dienststatus & Konfigurationsprüfung (`testparm`)
- System-Updates (`apt update`, `apt upgrade`, `apt autoremove`) mit Fortschrittsanzeige
- Dashboard mit Speicher, Updates und Neustart-Status
- **App-Update-Hinweis** – prüft GitHub auf neuere Versionen (Cache: 6 h)
- CSRF-Schutz & Login-Rate-Limiting
- Privilege-Daemon über Unix-Socket (kein sudo)

## Architektur

```
Browser (internes LAN / SSH-Tunnel)
        │
Gunicorn (User: samba-ui) – Flask-App
        │
        ├── liest /etc/samba/smb-shares.conf
        └── Unix-Socket → simple-samba-ui-priv (root)
                              ├── schreibt Freigaben + Backup
                              ├── testparm + smbd-Restart
                              └── apt-Operationen
```

## Voraussetzungen

- Debian 12/13 oder Ubuntu (mit `apt`)
- Root-Zugriff für Installation
- Samba-Datenverzeichnis (z. B. `/srv/shares`)

## Installation

### One-Liner (empfohlen)

```bash
curl -fsSL https://raw.githubusercontent.com/MarcelRuh/simple-samba/main/bootstrap.sh | sudo bash
```

Das Script klont das Repository nach `/usr/local/src/simple-samba`, installiert Abhängigkeiten, legt die App unter `/opt/simple-samba-ui` ab, erstellt Admin-Zugangsdaten und startet systemd-Dienste.

Am Ende werden **URL, Benutzername und Passwort** ausgegeben.

**Nicht-interaktiv** (eigene Werte statt Standard):

```bash
SIMPLE_SAMBA_BIND_HOST=192.168.1.10 \
SIMPLE_SAMBA_BIND_PORT=8080 \
SIMPLE_SAMBA_SHARES_BASE=/srv/shares \
curl -fsSL https://raw.githubusercontent.com/MarcelRuh/simple-samba/main/bootstrap.sh | sudo bash
```

### Manuell (git clone)

```bash
git clone https://github.com/MarcelRuh/simple-samba.git
cd simple-samba
sudo bash install.sh
```

### Bind-Adresse

| Adresse | Einsatz |
|---------|---------|
| `127.0.0.1` | Empfohlen – nur lokal / SSH-Tunnel |
| LAN-IP | Nur im vertrauenswürdigen internen Netz |
| `0.0.0.0` | Alle Interfaces – nur in isoliertem LAN |

Konfiguration: `/etc/simple-samba-ui/config.json`

## Updates

Nach Änderungen am Quellcode:

```bash
cd /usr/local/src/simple-samba   # oder dein Clone-Verzeichnis
git pull
sudo bash update.sh
```

## Deinstallation

```bash
sudo bash uninstall.sh
```

## Projektstruktur

```
simple-samba/
├── bootstrap.sh            # One-Liner-Einstieg (curl | bash)
├── install.sh / update.sh / uninstall.sh
├── app/                    # Flask-Anwendung
├── scripts/
│   ├── install-common.sh
│   └── simple-samba-ui-priv-daemon.py
└── etc/                    # systemd-Units, config.json.example
```

Nach Installation:

| Pfad | Inhalt |
|------|--------|
| `/opt/simple-samba-ui/` | App + Python-venv |
| `/etc/simple-samba-ui/config.json` | Konfiguration (chmod 600) |
| `/etc/samba/smb-shares.conf` | Verwaltete Freigaben |
| `/run/simple-samba-ui/priv.sock` | Privilege-Socket |

## Sicherheit

- Web-UI läuft **nicht als root**
- Admin-Passwort als **bcrypt-Hash**
- Kein TLS eingebaut – bei Bedarf SSH-Tunnel nutzen
- Nach Installation: Admin-Passwort ändern, `initial-password.txt` löschen
- Nicht ungefiltert ins Internet stellen

## Lizenz

MIT – siehe [LICENSE](LICENSE).
