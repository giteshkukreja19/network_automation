#!/bin/bash
set -e
USER_NAME="${LAB_USER:-admin}"
PASS="${LAB_PASSWORD:-labpassword}"

# --- SSH user + narrowly scoped passwordless sudo (vtysh only) ---
id "$USER_NAME" >/dev/null 2>&1 || adduser -D -s /bin/bash "$USER_NAME"
echo "$USER_NAME:$PASS" | chpasswd
VTYSH="$(command -v vtysh)"
echo "$USER_NAME ALL=(root) NOPASSWD: $VTYSH" > /etc/sudoers.d/lab
chmod 440 /etc/sudoers.d/lab
sed -i "s/^AllowUsers .*/AllowUsers $USER_NAME/" /etc/ssh/sshd_config
ssh-keygen -A >/dev/null

# --- FRR ---
mkdir -p /var/run/frr /var/log/frr
chown -R frr:frr /var/run/frr /var/log/frr /etc/frr
chmod 640 /etc/frr/frr.conf
bin() { for p in "/usr/lib/frr/$1" "/usr/sbin/$1" "/usr/bin/$1"; do [ -x "$p" ] && { echo "$p"; return; }; done; echo "missing FRR binary $1" >&2; exit 1; }
"$(bin zebra)"   -d -A 127.0.0.1
"$(bin staticd)" -d -A 127.0.0.1
"$(bin mgmtd)"   -d -A 127.0.0.1
sleep 2
vtysh -b || echo "vtysh -b reported an error (check frr.conf)"

echo "router ready: sshd + zebra + staticd"
exec /usr/sbin/sshd -D -e
