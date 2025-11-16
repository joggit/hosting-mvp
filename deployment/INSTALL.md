# Fresh Server Installation Guide

## Prerequisites

- Fresh Ubuntu 24.04 server
- Root access or sudo user
- Your GitHub repository URL

## Option 1: Full Automated Install (Fresh Server)

For a brand new server where you need to create users and configure security:
```bash
# Install sshpass (for password authentication)
# Ubuntu/Debian:
sudo apt-get install sshpass

# macOS:
brew install hudochenkov/sshpass/sshpass

# Run installation
python3 deployment/scripts/fresh_install.py \
  --server 75.119.141.162 \
  --user deploy \
  --repo https://github.com/yourusername/hosting-mvp.git \
  --root-password YOUR_ROOT_PASSWORD
```

This will:
1. ✅ Update system packages
2. ✅ Create deployment user
3. ✅ Setup SSH keys
4. ✅ Secure SSH (disable root login)
5. ✅ Configure firewall (UFW)
6. ✅ Setup fail2ban
7. ✅ Install dependencies
8. ✅ Deploy application
9. ✅ Configure nginx
10. ✅ Verify installation

## Option 2: Quick Install (Existing SSH Access)

If you already have SSH access to the server:
```bash
python3 deployment/scripts/quick_install.py \
  deploy@75.119.141.162 \
  https://github.com/yourusername/hosting-mvp.git
```

## Option 3: Manual Installation

### Step 1: Prepare Server
```bash
# SSH to server
ssh root@YOUR_SERVER_IP

# Update system
apt update && apt upgrade -y

# Create user
adduser deploy
usermod -aG sudo deploy
echo 'deploy ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/deploy

# Setup SSH keys
mkdir -p /home/deploy/.ssh
# Paste your public key:
echo "YOUR_SSH_PUBLIC_KEY" >> /home/deploy/.ssh/authorized_keys
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh

# Secure SSH
nano /etc/ssh/sshd_config
# Set: PermitRootLogin no
systemctl restart sshd

# Setup firewall
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 5000/tcp
ufw enable

# Setup fail2ban
apt install fail2ban
systemctl enable fail2ban
systemctl start fail2ban
```

### Step 2: Deploy Application
```bash
# SSH as deploy user
ssh deploy@YOUR_SERVER_IP

# Run the quick deploy script
curl -o ~/quick-deploy.sh https://raw.githubusercontent.com/yourusername/hosting-mvp/main/deployment/scripts/deploy.sh
chmod +x ~/quick-deploy.sh
./quick-deploy.sh https://github.com/yourusername/hosting-mvp.git
```

## Verification
```bash
# Check service status
ssh deploy@YOUR_SERVER_IP 'sudo systemctl status hosting-manager'

# Test API
curl http://YOUR_SERVER_IP:5000/api/health

# View logs
ssh deploy@YOUR_SERVER_IP 'sudo journalctl -u hosting-manager -f'
```

## Troubleshooting

### Service won't start
```bash
sudo journalctl -u hosting-manager -n 50
```

### Port already in use
```bash
sudo lsof -i :5000
sudo kill -9 PID
```

### Permission issues
```bash
sudo chown -R deploy:deploy /opt/hosting-manager
sudo chown -R deploy:deploy /var/lib/hosting-manager
```

### Update deployment
```bash
cd /opt/hosting-manager
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart hosting-manager
```

## Multi-Server Deployment

Deploy to multiple servers at once:
```bash
python3 deployment/scripts/fresh_install.py --server 192.168.1.10 --user deploy --repo URL &
python3 deployment/scripts/fresh_install.py --server 192.168.1.11 --user deploy --repo URL &
python3 deployment/scripts/fresh_install.py --server 192.168.1.12 --user deploy --repo URL &
wait
```

## Security Checklist

- [ ] Root login disabled
- [ ] SSH key authentication enabled
- [ ] Firewall configured (UFW)
- [ ] Fail2ban active
- [ ] Regular updates scheduled
- [ ] Backup strategy in place

## Next Steps

1. Configure SSL: `sudo certbot --nginx -d yourdomain.com`
2. Setup monitoring: Install monitoring tools
3. Configure backups: Setup automated backups
4. Add more features to your app
