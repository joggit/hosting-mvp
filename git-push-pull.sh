#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
SERVER="deploy@75.119.141.162"
REMOTE_PATH="/opt/hosting-manager"
SERVICE_NAME="hosting-manager"

echo -e "${BLUE}════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}        Git Push & Pull Deployment Script${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════${NC}"
echo ""

# ═══════════════════════════════════════════════════════════
# STEP 1: Check for uncommitted changes
# ═══════════════════════════════════════════════════════════
echo -e "${YELLOW}[1/6] Checking for local changes...${NC}"

if [[ -z $(git status -s) ]]; then
    echo -e "${GREEN}✅ No local changes to commit${NC}"
    SKIP_COMMIT=true
else
    echo -e "${YELLOW}📝 Found uncommitted changes:${NC}"
    git status -s
    SKIP_COMMIT=false
fi

echo ""

# ═══════════════════════════════════════════════════════════
# STEP 2: Commit changes (if any)
# ═══════════════════════════════════════════════════════════
if [ "$SKIP_COMMIT" = false ]; then
    echo -e "${YELLOW}[2/6] Committing changes...${NC}"
    
    # Prompt for commit message
    read -p "Enter commit message (or press Enter for default): " COMMIT_MSG
    
    if [ -z "$COMMIT_MSG" ]; then
        COMMIT_MSG="Update: $(date '+%Y-%m-%d %H:%M:%S')"
    fi
    
    git add .
    git commit -m "$COMMIT_MSG"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Changes committed${NC}"
    else
        echo -e "${RED}❌ Commit failed${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}[2/6] Skipping commit (no changes)${NC}"
fi

echo ""

# ═══════════════════════════════════════════════════════════
# STEP 3: Push to GitHub
# ═══════════════════════════════════════════════════════════
echo -e "${YELLOW}[3/6] Pushing to GitHub...${NC}"

git push origin main

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Pushed to GitHub${NC}"
else
    echo -e "${RED}❌ Push failed${NC}"
    exit 1
fi

echo ""

# ═══════════════════════════════════════════════════════════
# STEP 4: Pull changes on server
# ═══════════════════════════════════════════════════════════
echo -e "${YELLOW}[4/6] Pulling changes on server...${NC}"

ssh $SERVER << ENDSSH
cd $REMOTE_PATH

# Clean up any conflicts
echo "Cleaning up potential conflicts..."
rm -f .gitignore 2>/dev/null || true
git reset --hard HEAD 2>/dev/null || true

# Pull latest changes
echo "Pulling from GitHub..."
git pull origin main

if [ \$? -eq 0 ]; then
    echo "✅ Successfully pulled changes"
else
    echo "❌ Pull failed"
    exit 1
fi
ENDSSH

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Server updated${NC}"
else
    echo -e "${RED}❌ Server update failed${NC}"
    exit 1
fi

echo ""

# ═══════════════════════════════════════════════════════════
# STEP 5: Restart service
# ═══════════════════════════════════════════════════════════
echo -e "${YELLOW}[5/6] Restarting service...${NC}"

ssh $SERVER "sudo systemctl restart $SERVICE_NAME"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Service restarted${NC}"
    sleep 2
else
    echo -e "${RED}❌ Service restart failed${NC}"
    exit 1
fi

echo ""

# ═══════════════════════════════════════════════════════════
# STEP 6: Verify deployment
# ═══════════════════════════════════════════════════════════
echo -e "${YELLOW}[6/6] Verifying deployment...${NC}"

# Check service status
ssh $SERVER "sudo systemctl is-active $SERVICE_NAME" > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Service is running${NC}"
else
    echo -e "${RED}❌ Service is not running${NC}"
    echo -e "${YELLOW}Showing recent logs:${NC}"
    ssh $SERVER "sudo journalctl -u $SERVICE_NAME -n 20 --no-pager"
    exit 1
fi

# Test API health endpoint
echo -e "${YELLOW}Testing API health endpoint...${NC}"
HEALTH_CHECK=$(curl -s http://75.119.141.162:5000/api/health)

if [[ $HEALTH_CHECK == *"healthy"* ]]; then
    echo -e "${GREEN}✅ API is responding${NC}"
    echo -e "${GREEN}Response: $HEALTH_CHECK${NC}"
else
    echo -e "${RED}❌ API not responding${NC}"
fi

echo ""

# ═══════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════
echo -e "${BLUE}════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Deployment Complete!${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}Useful Commands:${NC}"
echo -e "  View logs:    ${YELLOW}ssh $SERVER 'sudo journalctl -u $SERVICE_NAME -f'${NC}"
echo -e "  Check status: ${YELLOW}ssh $SERVER 'sudo systemctl status $SERVICE_NAME'${NC}"
echo -e "  Test API:     ${YELLOW}curl http://75.119.141.162:5000/api/health${NC}"
echo ""
echo -e "${BLUE}Recent Logs:${NC}"
ssh $SERVER "sudo journalctl -u $SERVICE_NAME -n 10 --no-pager" | tail -10

echo ""
