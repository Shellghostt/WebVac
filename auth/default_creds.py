"""
default_creds.py — EyeWitness-inspired default credential checker.

Matches a page's URL, title, and server headers against a built-in database
of ~50 well-known vendor admin panels, returning any known default credentials.

Usage:
    checker = DefaultCredsChecker()
    matches = checker.check(url, title, server_header)
    # matches is a list[dict] — empty if no panel was recognised.
"""

from __future__ import annotations
import re
from urllib.parse import urlparse


# ── Credential database ───────────────────────────────────────────────────────
# Each entry:
#   "vendor"     : Human-readable vendor name
#   "panel"      : Specific panel / product name
#   "signatures" : List of strings to match against (url + title + server header)
#                  All matches are case-insensitive substring checks.
#   "username"   : Known default username (comma-sep if multiple)
#   "password"   : Known default password (comma-sep if multiple)
#   "notes"      : Extra context / variants
#   "reference"  : Official docs / advisory URL

DEFAULT_CREDS_DB: list[dict] = [
    # ── Network / Firewall appliances ─────────────────────────────────────────
    {
        "vendor": "Cisco",
        "panel": "Cisco ASA Web UI / ASDM",
        "signatures": ["cisco asa", "cisco asdm", "adaptive security appliance"],
        "username": "cisco",
        "password": "cisco",
        "notes": "Also try admin:(blank), enable password: cisco",
        "reference": "https://www.cisco.com/c/en/us/td/docs/security/asa/asa-cli-reference/S/asa-command-ref-S.html",
    },
    {
        "vendor": "Cisco",
        "panel": "Cisco IOS Web Interface",
        "signatures": ["cisco ios", "cisco router", "cisco switch", "ios web"],
        "username": "cisco",
        "password": "cisco",
        "notes": "Also try admin:admin",
        "reference": "https://www.cisco.com",
    },
    {
        "vendor": "Juniper",
        "panel": "Juniper J-Web",
        "signatures": ["juniper j-web", "junos web", "j-web", "juniper srx", "juniper ex"],
        "username": "root",
        "password": "",
        "notes": "Root has no default password on first boot; admin:juniper1 on some models",
        "reference": "https://www.juniper.net",
    },
    {
        "vendor": "pfSense",
        "panel": "pfSense Web UI",
        "signatures": ["pfsense", "pf sense"],
        "username": "admin",
        "password": "pfsense",
        "notes": "Changed post-install; older installs may still use defaults",
        "reference": "https://docs.netgate.com/pfsense/en/latest/usermanager/defaults.html",
    },
    {
        "vendor": "OPNsense",
        "panel": "OPNsense Web UI",
        "signatures": ["opnsense"],
        "username": "root",
        "password": "opnsense",
        "notes": "",
        "reference": "https://docs.opnsense.org",
    },
    {
        "vendor": "Fortinet",
        "panel": "FortiGate / FortiOS Web",
        "signatures": ["fortigate", "fortios", "fortinet", "fortimanager", "fortianalyzer"],
        "username": "admin",
        "password": "",
        "notes": "No password by default; some firmware forces a setup wizard",
        "reference": "https://docs.fortinet.com",
    },
    {
        "vendor": "Palo Alto Networks",
        "panel": "PAN-OS Web UI",
        "signatures": ["palo alto", "pan-os", "globalprotect portal"],
        "username": "admin",
        "password": "admin",
        "notes": "",
        "reference": "https://docs.paloaltonetworks.com",
    },
    {
        "vendor": "SonicWall",
        "panel": "SonicWall Management UI",
        "signatures": ["sonicwall", "sonic wall", "sonicos"],
        "username": "admin",
        "password": "password",
        "notes": "",
        "reference": "https://www.sonicwall.com",
    },
    {
        "vendor": "Netgear",
        "panel": "Netgear Router Admin",
        "signatures": ["netgear", "routerlogin.net"],
        "username": "admin",
        "password": "password",
        "notes": "Also try admin:1234",
        "reference": "https://kb.netgear.com",
    },
    {
        "vendor": "Linksys",
        "panel": "Linksys Router Admin",
        "signatures": ["linksys", "myrouter.local"],
        "username": "admin",
        "password": "admin",
        "notes": "Older models: (blank):admin",
        "reference": "https://www.linksys.com",
    },
    {
        "vendor": "Ubiquiti",
        "panel": "UniFi Controller / AirOS",
        "signatures": ["ubiquiti", "unifi", "airos", "edgeos", "edgerouter"],
        "username": "ubnt",
        "password": "ubnt",
        "notes": "UniFi Controller: admin:ubnt; EdgeOS: ubnt:ubnt",
        "reference": "https://help.ubnt.com",
    },
    {
        "vendor": "MikroTik",
        "panel": "MikroTik RouterOS / Winbox Web",
        "signatures": ["mikrotik", "routeros", "winbox"],
        "username": "admin",
        "password": "",
        "notes": "No password by default",
        "reference": "https://wiki.mikrotik.com",
    },
    {
        "vendor": "D-Link",
        "panel": "D-Link Router Admin",
        "signatures": ["d-link", "dlink"],
        "username": "admin",
        "password": "",
        "notes": "Password is blank; some models use admin:admin",
        "reference": "https://eu.dlink.com",
    },
    {
        "vendor": "TP-Link",
        "panel": "TP-Link Router Admin",
        "signatures": ["tp-link", "tplink", "tplinkwifi"],
        "username": "admin",
        "password": "admin",
        "notes": "Newer models generate unique passwords printed on the label",
        "reference": "https://www.tp-link.com",
    },
    {
        "vendor": "ASUS",
        "panel": "ASUS Router Admin",
        "signatures": ["asus router", "asuswrt", "asus wireless"],
        "username": "admin",
        "password": "admin",
        "notes": "",
        "reference": "https://www.asus.com",
    },

    # ── Web servers / App servers ─────────────────────────────────────────────
    {
        "vendor": "Apache",
        "panel": "Apache Tomcat Manager",
        "signatures": ["apache tomcat", "tomcat manager", "tomcat/", "/manager/html"],
        "username": "tomcat, admin, manager",
        "password": "tomcat, admin, manager, s3cret",
        "notes": "Check /manager/html and /host-manager/html",
        "reference": "https://tomcat.apache.org/tomcat-9.0-doc/manager-howto.html",
    },
    {
        "vendor": "JBoss / WildFly",
        "panel": "JBoss Management Console",
        "signatures": ["jboss", "wildfly", "jboss web console", "jboss admin"],
        "username": "admin",
        "password": "admin",
        "notes": "Also check /jmx-console and /web-console paths",
        "reference": "https://docs.wildfly.org",
    },
    {
        "vendor": "Oracle",
        "panel": "Oracle WebLogic Admin Console",
        "signatures": ["weblogic", "oracle weblogic", "/console/login", "weblogic server"],
        "username": "weblogic",
        "password": "weblogic, welcome1, weblogic1",
        "notes": "Very commonly left at defaults on enterprise environments",
        "reference": "https://docs.oracle.com/en/middleware/standalone/weblogic-server/",
    },
    {
        "vendor": "IBM",
        "panel": "IBM WebSphere Admin Console",
        "signatures": ["websphere", "ibm websphere", "/ibm/console"],
        "username": "admin, wsadmin",
        "password": "admin",
        "notes": "",
        "reference": "https://www.ibm.com/docs/en/was",
    },

    # ── DevOps / CI-CD / Monitoring ───────────────────────────────────────────
    {
        "vendor": "Jenkins",
        "panel": "Jenkins CI",
        "signatures": ["jenkins", "hudson ci"],
        "username": "admin",
        "password": "(check /var/jenkins_home/secrets/initialAdminPassword)",
        "notes": "Modern Jenkins generates a one-time setup password on first run",
        "reference": "https://www.jenkins.io/doc/book/installing/",
    },
    {
        "vendor": "Grafana",
        "panel": "Grafana Dashboard",
        "signatures": ["grafana", "grafana labs"],
        "username": "admin",
        "password": "admin",
        "notes": "Forces password change on first login in newer versions",
        "reference": "https://grafana.com/docs/grafana/latest/administration/configuration/",
    },
    {
        "vendor": "Kibana",
        "panel": "Kibana / Elasticsearch",
        "signatures": ["kibana", "elastic kibana"],
        "username": "elastic",
        "password": "(auto-generated; check enrollment token)",
        "notes": "Older OSS versions had no auth by default",
        "reference": "https://www.elastic.co/guide/en/elasticsearch/reference/current/security-minimal-setup.html",
    },
    {
        "vendor": "Prometheus",
        "panel": "Prometheus Metrics UI",
        "signatures": ["prometheus", "prometheus time series"],
        "username": "(none by default)",
        "password": "(none by default)",
        "notes": "No built-in auth — commonly exposed without protection",
        "reference": "https://prometheus.io/docs/prometheus/latest/configuration/https/",
    },
    {
        "vendor": "GitLab",
        "panel": "GitLab",
        "signatures": ["gitlab", "gitlab community", "gitlab enterprise"],
        "username": "root",
        "password": "(auto-generated; check /etc/gitlab/initial_root_password)",
        "notes": "Older versions: root:5iveL!fe",
        "reference": "https://docs.gitlab.com/ee/install/",
    },
    {
        "vendor": "Portainer",
        "panel": "Portainer Docker UI",
        "signatures": ["portainer", "portainer.io"],
        "username": "admin",
        "password": "admin, portainer",
        "notes": "First-run sets admin password via UI wizard",
        "reference": "https://docs.portainer.io",
    },
    {
        "vendor": "Rancher",
        "panel": "Rancher Kubernetes UI",
        "signatures": ["rancher", "rancher labs"],
        "username": "admin",
        "password": "admin",
        "notes": "",
        "reference": "https://docs.ranchermanager.rancher.io",
    },

    # ── CMS / Web applications ────────────────────────────────────────────────
    {
        "vendor": "WordPress",
        "panel": "WordPress Admin",
        "signatures": ["wordpress", "wp-admin", "wp-login", "wp login"],
        "username": "admin",
        "password": "admin, password, wordpress",
        "notes": "wp-login.php — extremely common target",
        "reference": "https://wordpress.org",
    },
    {
        "vendor": "Joomla",
        "panel": "Joomla Admin",
        "signatures": ["joomla", "/administrator"],
        "username": "admin",
        "password": "admin",
        "notes": "Check /administrator/index.php",
        "reference": "https://docs.joomla.org",
    },
    {
        "vendor": "Drupal",
        "panel": "Drupal Admin",
        "signatures": ["drupal", "/user/login"],
        "username": "admin",
        "password": "admin",
        "notes": "",
        "reference": "https://www.drupal.org/docs",
    },
    {
        "vendor": "Magento",
        "panel": "Magento Admin",
        "signatures": ["magento", "/admin_", "magento admin"],
        "username": "admin",
        "password": "admin123, magento",
        "notes": "Admin path is customisable — check common paths",
        "reference": "https://devdocs.magento.com",
    },
    {
        "vendor": "PrestaShop",
        "panel": "PrestaShop Admin",
        "signatures": ["prestashop", "presta shop"],
        "username": "admin@admin.com",
        "password": "admin, prestashop",
        "notes": "",
        "reference": "https://www.prestashop.com",
    },

    # ── Hosting control panels ────────────────────────────────────────────────
    {
        "vendor": "cPanel",
        "panel": "cPanel Web Hosting Panel",
        "signatures": ["cpanel", ":2082", ":2083", "whostmgr", ":2086", ":2087"],
        "username": "root, cpanel",
        "password": "(set during OS install)",
        "notes": "Port 2082/2083 (HTTP/S), WHM on 2086/2087",
        "reference": "https://docs.cpanel.net",
    },
    {
        "vendor": "Plesk",
        "panel": "Plesk Hosting Panel",
        "signatures": ["plesk", ":8443", ":8880"],
        "username": "admin",
        "password": "(set during install; check /etc/psa/.psa.shadow)",
        "notes": "Port 8880 (HTTP) or 8443 (HTTPS)",
        "reference": "https://docs.plesk.com",
    },
    {
        "vendor": "Webmin",
        "panel": "Webmin Admin",
        "signatures": ["webmin", ":10000"],
        "username": "root",
        "password": "(system root password)",
        "notes": "Default port 10000",
        "reference": "https://www.webmin.com",
    },
    {
        "vendor": "DirectAdmin",
        "panel": "DirectAdmin Panel",
        "signatures": ["directadmin", "direct admin", ":2222"],
        "username": "admin",
        "password": "(set during install)",
        "notes": "Port 2222",
        "reference": "https://www.directadmin.com",
    },

    # ── Database admin ────────────────────────────────────────────────────────
    {
        "vendor": "phpMyAdmin",
        "panel": "phpMyAdmin",
        "signatures": ["phpmyadmin", "pma", "phpmyadmin login"],
        "username": "root, pma",
        "password": "", 
        "notes": "Root often has no password on fresh WAMP/LAMP installs",
        "reference": "https://www.phpmyadmin.net",
    },
    {
        "vendor": "Adminer",
        "panel": "Adminer DB Manager",
        "signatures": ["adminer", "adminer.php"],
        "username": "root",
        "password": "",
        "notes": "Single-file PHP DB manager",
        "reference": "https://www.adminer.org",
    },
    {
        "vendor": "MongoDB",
        "panel": "MongoDB Express UI",
        "signatures": ["mongo express", "mongo-express"],
        "username": "admin",
        "password": "pass",
        "notes": "Common Docker default; check docker-compose env vars",
        "reference": "https://github.com/mongo-express/mongo-express",
    },
    {
        "vendor": "Redis",
        "panel": "RedisInsight / Redis Commander",
        "signatures": ["redis insight", "redis commander", "redisinsight"],
        "username": "(none)",
        "password": "(none by default)",
        "notes": "Redis itself has no auth unless configured",
        "reference": "https://redis.io/docs/management/security/",
    },

    # ── NAS / Storage ─────────────────────────────────────────────────────────
    {
        "vendor": "Synology",
        "panel": "Synology DiskStation Manager (DSM)",
        "signatures": ["synology", "diskstation", "dsm login"],
        "username": "admin",
        "password": "(blank by default on older DSM)",
        "notes": "DSM 7+ disables default admin account",
        "reference": "https://www.synology.com/en-global/knowledgebase",
    },
    {
        "vendor": "QNAP",
        "panel": "QNAP QTS Admin",
        "signatures": ["qnap", "qts admin", "qts login"],
        "username": "admin",
        "password": "admin",
        "notes": "",
        "reference": "https://www.qnap.com/en/how-to",
    },
    {
        "vendor": "FreeNAS / TrueNAS",
        "panel": "FreeNAS / TrueNAS Web UI",
        "signatures": ["freenas", "truenas", "ixsystems"],
        "username": "root",
        "password": "(set during install)",
        "notes": "",
        "reference": "https://www.truenas.com/docs/",
    },

    # ── IP Cameras / DVR ──────────────────────────────────────────────────────
    {
        "vendor": "Hikvision",
        "panel": "Hikvision IP Camera / DVR",
        "signatures": ["hikvision", "hikvision dvr", "hikvision nvr", "ds-2", "ivms"],
        "username": "admin",
        "password": "12345, admin",
        "notes": "Many models require password change on first login",
        "reference": "https://www.hikvision.com/en/support/",
    },
    {
        "vendor": "Dahua",
        "panel": "Dahua IP Camera / DVR",
        "signatures": ["dahua", "dahua dvr", "dahua nvr"],
        "username": "admin",
        "password": "admin",
        "notes": "",
        "reference": "https://www.dahuasecurity.com",
    },
    {
        "vendor": "Axis",
        "panel": "Axis Network Camera",
        "signatures": ["axis camera", "axis communications", "axis network"],
        "username": "root",
        "password": "pass",
        "notes": "Some firmware: admin:admin",
        "reference": "https://help.axis.com",
    },

    # ── Printers ──────────────────────────────────────────────────────────────
    {
        "vendor": "HP",
        "panel": "HP LaserJet / Embedded Web Server",
        "signatures": ["hp laserjet", "hp embedded web server", "hp ews", "hewlett-packard"],
        "username": "admin",
        "password": "(blank or printer serial number)",
        "notes": "Check label for serial; some models use admin:admin",
        "reference": "https://support.hp.com",
    },
    {
        "vendor": "Canon",
        "panel": "Canon imageRUNNER Web UI",
        "signatures": ["canon imagerunner", "canon web access", "canon printer"],
        "username": "Administrator",
        "password": "7654321",
        "notes": "",
        "reference": "https://www.usa.canon.com/support",
    },

    # ── Misc / Automation ─────────────────────────────────────────────────────
    {
        "vendor": "Home Assistant",
        "panel": "Home Assistant",
        "signatures": ["home assistant", "hassio", "hass.io"],
        "username": "(created on first run)",
        "password": "(created on first run)",
        "notes": "Older versions: homeassistant:(blank)",
        "reference": "https://www.home-assistant.io/docs/authentication/",
    },
    {
        "vendor": "Node-RED",
        "panel": "Node-RED Dashboard",
        "signatures": ["node-red", "nodered", "node red flow"],
        "username": "(none by default)",
        "password": "(none by default)",
        "notes": "Auth is disabled unless explicitly configured",
        "reference": "https://nodered.org/docs/user-guide/runtime/securing-node-red",
    },
    {
        "vendor": "Splunk",
        "panel": "Splunk Web",
        "signatures": ["splunk", "splunk enterprise", "splunk web"],
        "username": "admin",
        "password": "changeme",
        "notes": "Forces password change on first login in new versions",
        "reference": "https://docs.splunk.com",
    },
    {
        "vendor": "Zabbix",
        "panel": "Zabbix Monitoring",
        "signatures": ["zabbix", "zabbix frontend"],
        "username": "Admin",
        "password": "zabbix",
        "notes": "Capital A in Admin",
        "reference": "https://www.zabbix.com/documentation",
    },
    {
        "vendor": "Nagios",
        "panel": "Nagios Core / XI",
        "signatures": ["nagios", "nagiosxi", "nagios core"],
        "username": "nagiosadmin",
        "password": "nagiosadmin",
        "notes": "XI uses admin:admin",
        "reference": "https://www.nagios.org/documentation/",
    },
]


# ── Checker class ─────────────────────────────────────────────────────────────

class DefaultCredsChecker:
    """
    Checks a page against the built-in vendor default credential database.

    Usage::

        checker = DefaultCredsChecker()
        matches = checker.check(
            url="https://192.168.1.1:8080/manager/html",
            title="Apache Tomcat/9.0.65",
            server_header="Apache-Coyote/1.1",
        )
        # [{'vendor': 'Apache', 'panel': 'Apache Tomcat Manager', ...}]
    """

    def __init__(self) -> None:
        self._db = DEFAULT_CREDS_DB

    def check(
        self,
        url: str = "",
        title: str = "",
        server_header: str = "",
    ) -> list[dict]:
        """
        Match the page against the credential database.

        Args:
            url:           The page URL.
            title:         The page ``<title>`` text.
            server_header: The ``Server`` HTTP response header value.

        Returns:
            List of matching credential entries (dicts).  Empty if no match.
        """
        # Build a single searchable string from all available signals
        haystack = " ".join([
            url.lower(),
            title.lower(),
            server_header.lower(),
        ])

        matches: list[dict] = []
        seen_vendors: set[str] = set()

        for entry in self._db:
            vendor_key = f"{entry['vendor']}|{entry['panel']}"
            if vendor_key in seen_vendors:
                continue

            for sig in entry["signatures"]:
                if sig.lower() in haystack:
                    seen_vendors.add(vendor_key)
                    matches.append({
                        "vendor":    entry["vendor"],
                        "panel":     entry["panel"],
                        "username":  entry["username"],
                        "password":  entry["password"],
                        "notes":     entry["notes"],
                        "reference": entry["reference"],
                    })
                    break  # matched — no need to check more signatures

        return matches

    def summary(self) -> str:
        """Return a human-readable summary of the database size."""
        return f"DefaultCredsChecker: {len(self._db)} vendor entries loaded."
