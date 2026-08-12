# FRRouting on Alpine (Alpine publishes aarch64 packages -> native ARM64, no emulation)
FROM alpine:3.20
RUN apk add --no-cache frr openssh sudo bash iproute2 busybox-extras
COPY daemons /etc/frr/daemons
COPY frr.conf /etc/frr/frr.conf
COPY sshd_config /etc/ssh/sshd_config
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
