#!/bin/bash
set -e
cd "/Users/vijai/Documents/Final Trading strategy/nifty-alpha-bot"
SSH="ssh -i ~/.ssh/nifty-bot-key.pem -o StrictHostKeyChecking=no"

echo "=== Syncing files ==="
rsync -az -e "$SSH" \
  api/main.py \
  bot/trader.py \
  shared/regime_detector.py \
  backtest/backtest_engine.py \
  dashboard/src/pages/LogsPage.tsx \
  dashboard/src/pages/Dashboard.tsx \
  dashboard/src/components/panels/LivePnLPanel.tsx \
  ubuntu@15.207.47.244:/tmp/nifty_update/

echo "=== Deploying on EC2 ==="
$SSH ubuntu@15.207.47.244 bash << 'REMOTE'
  set -e
  cp /tmp/nifty_update/main.py            /opt/nifty-bot/nifty-alpha-bot/api/main.py
  cp /tmp/nifty_update/trader.py          /opt/nifty-bot/nifty-alpha-bot/bot/trader.py
  cp /tmp/nifty_update/regime_detector.py /opt/nifty-bot/nifty-alpha-bot/shared/regime_detector.py
  cp /tmp/nifty_update/backtest_engine.py /opt/nifty-bot/nifty-alpha-bot/backtest/backtest_engine.py
  cp /tmp/nifty_update/LogsPage.tsx       /opt/nifty-bot/nifty-alpha-bot/dashboard/src/pages/LogsPage.tsx
  cp /tmp/nifty_update/Dashboard.tsx      /opt/nifty-bot/nifty-alpha-bot/dashboard/src/pages/Dashboard.tsx
  cp /tmp/nifty_update/LivePnLPanel.tsx   /opt/nifty-bot/nifty-alpha-bot/dashboard/src/components/panels/LivePnLPanel.tsx
  cd /opt/nifty-bot/nifty-alpha-bot
  docker compose build --no-cache bot api dashboard
  docker compose up -d
  docker compose restart nginx
  docker compose ps
REMOTE
echo "=== Done ==="
