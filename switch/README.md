# Switch node

* `Dockerfile`, `entrypoint.sh`, `sshd_config` - **Implementation B**: Alpine + Linux bridge `br0` with veth ports `port1..port4`,
  managed through the custom NAPALM driver (`backend/linux_switch_driver.py`).
* `configuration/ceos-startup.cfg` - **Implementation A**: startup config for Arista cEOS (enables eAPI/HTTPS, user `admin`).
