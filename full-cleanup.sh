#!/bin/bash

NAME="${1:-datablox.co.za}"
SERVER="deploy@75.119.141.162"

echo "🧹 Complete cleanup for: $NAME"
echo ""

ssh $SERVER << ENDSSH
echo "1. Stopping PM2 process..."
pm2 delete $NAME 2>/dev/null || echo "  (no PM2 process)"
pm2 save

echo "2. Removing from database..."
sqlite3 /var/lib/hosting-manager/hosting.db << 'SQL'
DELETE FROM domains WHERE domain_name = '$NAME' OR app_name = '$NAME';
DELETE FROM processes WHERE name = '$NAME';
DELETE FROM deployment_logs WHERE domain_name = '$NAME';
SQL

echo "3. Removing nginx config..."
sudo rm -f /etc/nginx/sites-available/$NAME
sudo rm -f /etc/nginx/sites-enabled/$NAME
sudo nginx -t && sudo systemctl reload nginx

echo "4. Removing application files..."
sudo rm -rf /var/www/domains/$NAME

echo ""
echo "✅ Complete cleanup done for: $NAME"
echo ""

# Verify cleanup
echo "Verification:"
echo "  Files: $(ls /var/www/domains/ | grep $NAME | wc -l) (should be 0)"
echo "  DB domains: $(sqlite3 /var/lib/hosting-manager/hosting.db "SELECT COUNT(*) FROM domains WHERE domain_name='$NAME';")"
echo "  DB processes: $(sqlite3 /var/lib/hosting-manager/hosting.db "SELECT COUNT(*) FROM processes WHERE name='$NAME';")"
ENDSSH

echo ""
echo "Ready to redeploy!"
