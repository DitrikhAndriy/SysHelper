"""Compact network report; expanded inventory and original errors in details."""

import ipaddress

from ..collectors.network import collect_network_snapshot
from ..report_utils import NA, aligned_row as row, block


def collect_network():
    return format_network(collect_network_snapshot())


def _joined(items):
    return ", ".join(str(item) for item in items or []) or NA


def _address_text(ip, details):
    text = f"{ip['Address']}/{ip['Prefix']}"
    if ip.get("State") not in (None, "Preferred"):
        text += f" ({ip['State']})"
    local = ":" in ip["Address"] and ipaddress.ip_address(ip["Address"]).is_link_local
    origin = "Link-local" if local else {
        "Dhcp": "DHCP", "RouterAdvertisement": "Router advertisement", "WellKnown": "Automatic"
    }.get(ip.get("Origin"), ip.get("Origin"))
    if origin and (details or local):
        text += f" · {origin}"
    return text


def _rate(item):
    if item is None:
        return NA
    bits = item * 8
    return f"{bits / 1_000_000:.2f} Mbit/s" if bits >= 1_000_000 else f"{bits / 1000:.1f} Kbit/s"


def _apipa(adapter):
    return any(ipaddress.ip_address(ip["Address"]) in ipaddress.ip_network("169.254.0.0/16")
               for ip in adapter.get("IPv4") or [])


def _list_rows(label, items, empty="None"):
    items = list(items or [])
    return [row(label if index == 0 else "", item) for index, item in enumerate(items)] or [row(label, empty)]


def _configuration_rows(adapter, errors, details=False):
    """Keep the useful ipconfig fields together, including each address's mask."""
    status = adapter.get("Status") or NA
    if adapter.get("Profile"):
        status += f" · {adapter['Profile']}"
    rows = [row("Adapter", adapter.get("Description")), row("Status", status),
            row("MAC", adapter.get("MAC")), row("Link speed", adapter.get("LinkSpeed")),
            row("DHCP (IPv4)", adapter.get("DHCPv4"))]
    for ip in adapter.get("IPv4") or []:
        rows += [row("IPv4", _address_text(ip, details)),
                 row("Subnet mask", str(ipaddress.IPv4Network(f"0.0.0.0/{ip['Prefix']}").netmask))]
    if not adapter.get("IPv4"):
        rows.append(row("IPv4", NA if "Addresses" in errors else "None"))
    if details or not adapter.get("IPv4"):
        rows += _list_rows("IPv6", (_address_text(ip, details) for ip in adapter.get("IPv6") or []),
                           NA if "Addresses" in errors else "None")
    rows += _list_rows("Gateway", adapter.get("Gateways"), NA if "Routes" in errors else "None")
    rows += _list_rows("DNS servers", adapter.get("DNS"), NA if "DNS configuration" in errors else "None")
    rows.append(row("DNS suffix", adapter.get("Suffix") or (NA if "DNS suffix" in errors else "None")))
    if adapter.get("DHCPv4") == "Enabled":
        rows.append(row("DHCP server", adapter.get("DHCPServer")))
        if details:
            rows += [row("Lease obtained", adapter.get("LeaseObtained")), row("Lease expires", adapter.get("LeaseExpires"))]
    if details:
        for family in ("IPv4", "IPv6"):
            if adapter.get(f"Windows{family}"):
                rows.append(row(f"Windows {family}", adapter[f"Windows{family}"]))
        if adapter.get("RegisterDNS") is not None:
            rows.append(row("Register DNS", "Enabled" if adapter["RegisterDNS"] else "Disabled"))
        rows += [row("Send", _rate(adapter.get("Send"))), row("Receive", _rate(adapter.get("Receive")))]
    return rows


def _ping_result(check):
    if check.get("Sent") is None:
        return check.get("Result") or check.get("Error")
    timing = f"avg {check['Average']:.1f} ms" if check.get("Average") is not None else "No ICMP reply"
    return f"{timing} · loss {check['Loss']:.0f}% ({check['Received']}/{check['Sent']})"


def _dns_status(check):
    latency = f" · {check['Milliseconds']:.1f} ms" if check.get("Milliseconds") is not None else ""
    return f"{check['Server']} [{check['Status']}]{latency}"


def _dns_blocks(checks, details=False):
    configured, public, expanded = [], [], []
    providers = {}
    for check in checks:
        if check.get("ConfiguredOn"):
            configured.append(row(check["Server"], f"[{check['Status']}]" +
                              (f" · {check['Milliseconds']:.1f} ms" if check.get("Milliseconds") is not None else "")))
        if check.get("Provider"):
            providers.setdefault(check["Provider"], []).append(check)
        if details:
            rows = [row("Server", _dns_status(check)), row("Query", f"{check.get('Host', NA)} · A")]
            if check.get("ConfiguredOn"):
                rows.append(row("Configured on", _joined(check["ConfiguredOn"])))
            if check.get("Addresses"):
                rows.append(row("Answer", _joined(check["Addresses"])))
            if check.get("Error"):
                rows.append(row("Error", check["Error"]))
            expanded.append("\n".join(rows))
    for provider, group in providers.items():
        public.extend(row(provider if index == 0 else "", _dns_status(check)) for index, check in enumerate(group))
    blocks = [block("CONFIGURED DNS", configured or ["None"]), block("PUBLIC DNS", public or [NA])]
    if details:
        blocks.append(block("DNS QUERY DETAILS", "\n\n".join(expanded).splitlines()))
    return blocks


def format_network(data):
    errors = data.get("Errors") or []
    failed_sources = {e["Source"] for e in errors}
    checks = data.get("Checks") or []
    by_name = {check["Name"]: check for check in checks}
    internet = by_name.get("Internet", {})
    dns = by_name.get("DNS", {})
    tcp = by_name.get("Public TCP", {})
    summary_checks, detail_checks = [], []
    for check in checks:
        ping = check["Name"] in ("Gateway", "Public ping")
        result = _ping_result(check) if ping else check.get("Result")
        # Successful auxiliary probes stay in details; avoid repeating "OK" rows.
        if check["Name"] != "Internet" and (check["Status"] != "OK" or ping):
            target = f" {check['Target']}" if check.get("Target") and ping else ""
            summary_checks.append(row(check["Name"], f"[{check['Status']}]{target}" +
                                     (f" · {result}" if result else "")))
        check_rows = [row("Status", f"[{check['Status']}]"), row("Target", check.get("Target")),
                      row("Result", result or check.get("Error"))]
        if ping:
            if check.get("Minimum") is not None:
                check_rows.append(row("Min / max", f"{check['Minimum']} / {check['Maximum']} ms"))
            if check.get("Replies"):
                check_rows.append(row("Replies", _joined(check["Replies"])))
            check_rows.extend(row("Error", error) for error in check.get("Errors") or [])
        detail_checks.append(block(check["Name"].upper(), check_rows))
    if internet.get("Status") == "OK":
        summary_checks[0:0] = [row("Connection", "[OK] Internet probe passed")]
    elif internet:
        summary_checks[0:0] = [row("Connection", "[WARNING] Internet access not confirmed")]
    else:
        summary_checks[0:0] = [row("Connection", NA)]
    hints = []
    if internet.get("Status") != "OK":
        if dns.get("Status") == "FAILED":
            hints.append("[WARNING] DNS lookup failed; check configured DNS servers.")
        if tcp.get("Status") == "OK":
            hints.append("Public TCP is reachable; the web probe may be blocked by a proxy, sign-in page or filtering.")
        elif tcp:
            hints.append("Public TCP and web access were not confirmed; check routing, VPN, proxy or firewall.")
    if any(check["Name"] == "Gateway" and check["Status"] == "WARNING" for check in checks):
        hints.append("Gateway ICMP sample has missing replies; ping may be blocked.")
    if any(check["Name"] == "Public ping" and check["Status"] == "WARNING" for check in checks):
        hints.append("External ICMP sample has missing replies; ping may be blocked.")
    if any(check["Name"] == "Gateway" and check["Status"] == "ERROR" for check in checks):
        hints.append("Gateway check could not run; see the original error in details.")

    brief_adapters, full_adapters = [], []
    adapters = data.get("Adapters") or []
    active = [a for a in adapters if a.get("Status") == "Up"]
    if adapters and not active:
        hints.append("[WARNING] No adapter has an active link.")
    for adapter in adapters:
        title = adapter.get("Name") or "Adapter"
        if adapter.get("Status") == "Up":
            brief_adapters.append(block(title, _configuration_rows(adapter, failed_sources)))
            if _apipa(adapter):
                hints.append(f"[WARNING] {title}: self-assigned IPv4 address; DHCP may be unavailable.")
            for ip in (adapter.get("IPv4") or []) + (adapter.get("IPv6") or []):
                if ip.get("State") in ("Duplicate", "Invalid", "Tentative"):
                    hints.append(f"[WARNING] {title}: {ip['Address']} · {ip['State']}")
            full_adapters.append(block(title, _configuration_rows(adapter, failed_sources, True)))
        else:
            # Disconnected interfaces need no empty IP/DNS/DHCP inventory.
            full_adapters.append(block(title, [row("Adapter", adapter.get("Description")),
                                               row("Status", adapter.get("Status")), row("MAC", adapter.get("MAC"))]))
    identity = data.get("Identity") or {}
    identity_rows = [row("Host name", identity.get("HostName")),
                     row("Primary suffix", identity.get("PrimarySuffix") or
                         (NA if "Network identity" in failed_sources else "None")),
                     *_list_rows("DNS search", identity.get("SearchList"), NA if "Global DNS" in failed_sources else "None")]
    brief = [block("NETWORK", identity_rows), block("ADAPTERS", ["\n\n".join(brief_adapters)] if brief_adapters else [NA]),
             block("CONNECTIVITY", summary_checks)]
    detailed = [block("NETWORK", identity_rows), block("ADAPTERS", ["\n\n".join(full_adapters)] if full_adapters else [NA])]
    routes = data.get("Routes") or []
    detailed.append(block("DEFAULT ROUTES", [
        f"{route['Prefix']} → {route['Gateway']} · {route['Interface']} · metric {route['Metric']}"
        for route in routes] or ["None"]))
    proxy = data.get("Proxy")
    if proxy:
        detailed.append(block("USER PROXY", [row("Manual proxy", "Enabled" if proxy.get("UserProxyEnabled") else "Disabled"),
                                              row("PAC URL", "Configured" if proxy.get("PACConfigured") else "None")]))
    if any(check.get("ConfiguredOn") and check["Status"] != "OK" for check in data.get("DNSChecks") or []):
        hints.append("A configured DNS check failed; see details.")
    if hints:
        brief.append(block("NOTES", hints))
        detailed.append(block("NOTES", hints))
    if data.get("DNSChecks"):
        brief.extend(_dns_blocks(data["DNSChecks"]))
        detailed.extend(_dns_blocks(data["DNSChecks"], details=True))
    detailed.append(block("CHECKS", ["\n\n".join(detail_checks)] if detail_checks else [NA]))
    if errors:
        brief.append("[WARNING] Some information is unavailable. See details.")
        detailed.append(block("COLLECTION ERRORS", [f"{e['Source']}\n{e['Error']}" for e in errors]))
    return "\n\n".join(brief), "\n\n".join(detailed)
