#!/bin/bash
set -e
cd "/Users/vijai/Documents/Final Trading strategy/nifty-alpha-bot"
SSH="ssh -i ~/.ssh/nifty-bot-key.pem -o StrictHostKeyChecking=no"
EC2="ubuntu@15.207.47.244"
REMOTE_DIR="/opt/nifty-bot/nifty-alpha-bot"

echo "=== Syncing files to EC2 ==="
$SSH $EC2 "mkdir -p /tmp/nifty_update/backtest /tmp/nifty_update/bot /tmp/nifty_update/shared /tmp/nifty_update/dashboard/src/stores /tmp/nifty_update/dashboard/src/hooks /tmp/nifty_update/dashboard/src/pages"

rsync -az -e "$SSH" api/main.py                                    $EC2:/tmp/nifty_update/
rsync -az -e "$SSH" bot/trader.py                                   $EC2:/tmp/nifty_update/bot/
rsync -az -e "$SSH" shared/impulse_detector.py                     $EC2:/tmp/nifty_update/shared/
rsync -az -e "$SSH" backtest/daily_backtest_engine.py              $EC2:/tmp/nifty_update/backtest/
rsync -az -e "$SSH" backtest/bull_backtest_engine.py               $EC2:/tmp/nifty_update/backtest/
rsync -az -e "$SSH" backtest/combined_runner.py                    $EC2:/tmp/nifty_update/backtest/
rsync -az -e "$SSH" backtest/metrics.py                            $EC2:/tmp/nifty_update/backtest/
rsync -az -e "$SSH" dashboard/src/pages/Dashboard.tsx              $EC2:/tmp/nifty_update/dashboard/src/pages/
rsync -az -e "$SSH" dashboard/src/stores/tradingStore.ts           $EC2:/tmp/nifty_update/dashboard/src/stores/
rsync -az -e "$SSH" dashboard/src/hooks/useWebSocket.ts            $EC2:/tmp/nifty_update/dashboard/src/hooks/

echo "=== Copying to app directory ==="
$SSH $EC2 bash << REMOTE
  set -e
  cp /tmp/nifty_update/main.py                        $REMOTE_DIR/api/main.py
  cp /tmp/nifty_update/bot/trader.py                  $REMOTE_DIR/bot/trader.py
  cp /tmp/nifty_update/shared/impulse_detector.py     $REMOTE_DIR/shared/impulse_detector.py
  cp /tmp/nifty_update/backtest/daily_backtest_engine.py  $REMOTE_DIR/backtest/daily_backtest_engine.py
  cp /tmp/nifty_update/backtest/bull_backtest_engine.py   $REMOTE_DIR/backtest/bull_backtest_engine.py
  cp /tmp/nifty_update/backtest/combined_runner.py        $REMOTE_DIR/backtest/combined_runner.py
  cp /tmp/nifty_update/backtest/metrics.py                $REMOTE_DIR/backtest/metrics.py
  cp /tmp/nifty_update/dashboard/src/pages/Dashboard.tsx       $REMOTE_DIR/dashboard/src/pages/Dashboard.tsx
  cp /tmp/nifty_update/dashboard/src/stores/tradingStore.ts    $REMOTE_DIR/dashboard/src/stores/tradingStore.ts
  cp /tmp/nifty_update/dashboard/src/hooks/useWebSocket.ts     $REMOTE_DIR/dashboard/src/hooks/useWebSocket.ts
  cd $REMOTE_DIR
  docker compose build --no-cache bot api dashboard
  docker compose up -d
  docker compose restart nginx
  docker compose ps
REMOTE
echo "=== Deploy complete ==="
