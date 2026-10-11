#!/bin/bash
set -e
USER_NAME="${LAB_USER:-admin}"
PASS="${LAB_PASSWORD:-labpassword}"
id "$USER_NAME" >/dev/null 2>&1 || adduser -D -s /bin/bash "$USER_NAME"
echo "$USER_NAME:$PASS" | chpasswd
# passwordless sudo ONLY for the ip command (used to set interface aliases = descriptions)
echo "$USER_NAME ALL=(root) NOPASSWD: /sbin/ip, /bin/ip, /usr/sbin/ip" > /etc/sudoers.d/lab
chmod 440 /etc/sudoers.d/lab
sed -i "s/^AllowUsers .*/AllowUsers $USER_NAME/" /etc/ssh/sshd_config
ssh-keygen -A >/dev/null

# Real Linux bridge with 4 veth "front panel" ports (port1..port4)
ip link add br0 type bridge 2>/dev/null || true
ip link set br0 up
for i in 1 2 3 4; do
  ip link add "port$i" type veth peer name "port$i-peer" 2>/dev/null || true
  ip link set "port$i" master br0
  ip link set "port$i" up
  ip link set "port$i-peer" up
done
echo "switch ready: br0 + port1..port4 + sshd"
exec /usr/sbin/sshd -D -e
