#!/bin/bash
set -e

# ─── NIFTY ALPHA BOT — CLOUD DEPLOYMENT SCRIPT ──────────────────
# Run on a fresh Ubuntu 22.04+ server (AWS EC2, GCP, DigitalOcean, etc.)
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh          # Full setup (first time)
#   ./deploy.sh update   # Rebuild and restart (code updates)
#   ./deploy.sh logs     # Tail live logs
#   ./deploy.sh status   # Check all services
#   ./deploy.sh token YOUR_TOKEN  # Set today's Kite token

BOLD='\033[1m'
GREEN='\033[92m'
RED='\033[91m'
YELLOW='\033[93m'
CYAN='\033[96m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

case "${1:-setup}" in

# ─── INITIAL SETUP ───────────────────────────────────────────────
setup)
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════${NC}"
    echo -e "${BOLD}  NIFTY ALPHA BOT — CLOUD DEPLOYMENT${NC}"
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════${NC}"

    # 1. Install Docker if not present
    if ! command -v docker &>/dev/null; then
        echo -e "\n${YELLOW}Installing Docker...${NC}"
        curl -fsSL https://get.docker.com | sh
        sudo usermod -aG docker "$USER"
        echo -e "${GREEN}Docker installed. You may need to log out and back in.${NC}"
    else
        echo -e "${GREEN}✓ Docker already installed${NC}"
    fi

    # 2. Install Docker Compose plugin if not present
    if ! docker compose version &>/dev/null; then
        echo -e "\n${YELLOW}Installing Docker Compose plugin...${NC}"
        sudo apt-get update && sudo apt-get install -y docker-compose-plugin
    else
        echo -e "${GREEN}✓ Docker Compose ready${NC}"
    fi

    # 3. Set timezone to IST
    echo -e "\n${YELLOW}Setting timezone to Asia/Kolkata (IST)...${NC}"
    sudo timedatectl set-timezone Asia/Kolkata 2>/dev/null || true
    echo -e "${GREEN}✓ Timezone: $(date +%Z)${NC}"

    # 4. Check .env
    if [ ! -f .env ]; then
        echo -e "\n${YELLOW}Creating .env from template...${NC}"
        cp .env.example .env
        echo -e "${RED}╔══════════════════════════════════════════╗${NC}"
        echo -e "${RED}║  IMPORTANT: Edit .env with your values!  ║${NC}"
        echo -e "${RED}║  nano .env                               ║${NC}"
        echo -e "${RED}╚══════════════════════════════════════════╝${NC}"
        echo ""
        echo "Required fields:"
        echo "  KITE_API_KEY=..."
        echo "  KITE_API_SECRET=..."
        echo "  KITE_USER_ID=..."
        echo "  KITE_USER_PASSWORD=..."
        echo "  POSTGRES_PASSWORD=...  (any strong password)"
        echo ""
        echo "Optional but recommended:"
        echo "  KITE_TOTP_SECRET=...   (for auto token refresh)"
        echo "  TELEGRAM_BOT_TOKEN=... (for trade notifications)"
        echo "  TELEGRAM_CHAT_ID=..."
        echo ""
        echo -e "After editing, run: ${CYAN}./deploy.sh${NC} again"
        exit 0
    fi

    echo -e "${GREEN}✓ .env file found${NC}"

    # 5. Build and start
    echo -e "\n${YELLOW}Building containers...${NC}"
    docker compose build --no-cache

    echo -e "\n${YELLOW}Starting services...${NC}"
    docker compose up -d

    echo -e "\n${YELLOW}Waiting for services to start...${NC}"
    sleep 10

    # 6. Status check
    echo -e "\n${BOLD}Service Status:${NC}"
    docker compose ps

    echo -e "\n${GREEN}${BOLD}═══════════════════════════════════════${NC}"
    echo -e "${GREEN}${BOLD}  DEPLOYMENT COMPLETE!${NC}"
    echo -e "${GREEN}${BOLD}═══════════════════════════════════════${NC}"
    echo ""
    echo -e "Dashboard: ${CYAN}http://$(hostname -I | awk '{print $1}')${NC}"
    echo -e "API:       ${CYAN}http://$(hostname -I | awk '{print $1}')/api/status${NC}"
    echo ""
    echo -e "Commands:"
    echo -e "  ${CYAN}./deploy.sh logs${NC}             — View live bot logs"
    echo -e "  ${CYAN}./deploy.sh status${NC}           — Check service status"
    echo -e "  ${CYAN}./deploy.sh token TOKEN${NC}      — Set Kite token"
    echo -e "  ${CYAN}./deploy.sh update${NC}           — Rebuild after code changes"
    echo -e "  ${CYAN}./deploy.sh restart${NC}          — Restart all services"
    echo -e "  ${CYAN}./deploy.sh stop${NC}             — Stop everything"
    ;;

# ─── UPDATE (rebuild + restart) ──────────────────────────────────
update)
    echo -e "${YELLOW}Rebuilding and restarting...${NC}"
    docker compose build --no-cache
    docker compose up -d
    echo -e "${GREEN}✓ Updated and restarted${NC}"
    docker compose ps
    ;;

# ─── RESTART ─────────────────────────────────────────────────────
restart)
    echo -e "${YELLOW}Restarting services...${NC}"
    docker compose restart
    echo -e "${GREEN}✓ Restarted${NC}"
    docker compose ps
    ;;

# ─── STOP ────────────────────────────────────────────────────────
stop)
    echo -e "${YELLOW}Stopping all services...${NC}"
    docker compose down
    echo -e "${GREEN}✓ Stopped${NC}"
    ;;

# ─── LOGS ────────────────────────────────────────────────────────
logs)
    SERVICE="${2:-bot}"
    echo -e "${CYAN}Tailing logs for: ${SERVICE}${NC}"
    docker compose logs -f --tail=100 "$SERVICE"
    ;;

# ─── STATUS ──────────────────────────────────────────────────────
status)
    echo -e "${BOLD}Service Status:${NC}"
    docker compose ps
    echo ""

    # Check bot state
    echo -e "${BOLD}Bot State:${NC}"
    docker compose exec bot python -c "
import json, os
from pathlib import Path
SD = Path(os.environ.get('STATE_DIR', '/app/state'))
pos = SD / 'kite_bot_position.json'
tok = SD / 'kite_token_cache.json'
evt = SD / 'kite_bot_events.jsonl'
halt = SD / 'kite_bot_halt.flag'

print(f'  Position: {json.loads(pos.read_text()).get(\"state\", \"?\") if pos.exists() else \"IDLE (no file)\"}')
print(f'  Token: {\"valid\" if tok.exists() and json.loads(tok.read_text()).get(\"date\") == __import__(\"datetime\").date.today().isoformat() else \"STALE/MISSING\"}')
print(f'  Events: {len(evt.read_text().strip().split(chr(10))) if evt.exists() else 0}')
print(f'  Halt flag: {\"ACTIVE ⚠️\" if halt.exists() else \"Not set\"}')
" 2>/dev/null || echo "  Could not read bot state"
    ;;

# ─── SET TOKEN ───────────────────────────────────────────────────
token)
    TOKEN="$2"
    if [ -z "$TOKEN" ]; then
        echo -e "${RED}Usage: ./deploy.sh token YOUR_KITE_ACCESS_TOKEN${NC}"
        exit 1
    fi

    # Write to token cache inside the container
    docker compose exec bot python -c "
import json, os
from datetime import date, datetime
from pathlib import Path
SD = Path(os.environ.get('STATE_DIR', '/app/state'))
data = {'access_token': '$TOKEN', 'date': date.today().isoformat(), 'saved_at': datetime.now().isoformat()}
(SD / 'kite_token_cache.json').write_text(json.dumps(data))
print(f'Token saved for {date.today()}')
"
    echo -e "${GREEN}✓ Token set. Restart bot to pick it up:${NC}"
    echo -e "  ${CYAN}docker compose restart bot${NC}"
    ;;

# ─── HELP ────────────────────────────────────────────────────────
*)
    echo "Usage: ./deploy.sh [command]"
    echo ""
    echo "Commands:"
    echo "  setup     Full setup (default)"
    echo "  update    Rebuild and restart"
    echo "  restart   Restart services"
    echo "  stop      Stop everything"
    echo "  logs      Tail bot logs (or: logs api, logs watchdog)"
    echo "  status    Check all services + bot state"
    echo "  token T   Set Kite access token for today"
    ;;

esac
