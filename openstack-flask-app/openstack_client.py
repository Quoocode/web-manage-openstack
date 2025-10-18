import requests, yaml
import base64
import os

# ======================
# AUTHENTICATION (Keystone)
# ======================
def get_conn():
    # 🔹 1. Đọc file clouds.yaml
    with open("/home/phucdo/.config/openstack/clouds.yaml", "r") as f:
        config = yaml.safe_load(f)

    cloud = config["clouds"]["mycloud"]
    auth = cloud["auth"]

    auth_url = auth["auth_url"]
    username = auth["username"]
    password = auth["password"]
    project_name = auth["project_name"]
    user_domain_name = auth["user_domain_name"]
    project_domain_name = auth["project_domain_name"]

    # 🔹 2. Payload xác thực
    payload = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": username,
                        "domain": {"name": user_domain_name},
                        "password": password,
                    }
                }
            },
            "scope": {
                "project": {
                    "name": project_name,
                    "domain": {"name": project_domain_name}
                }
            },
        }
    }

    headers = {"Content-Type": "application/json"}

    # 🔹 3. Gửi POST đến Keystone để lấy token
    url = f"{auth_url}/auth/tokens"
    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 201:
        raise Exception(f"❌ Authentication failed: {response.text}")

    token = response.headers["X-Subject-Token"]
    token_info = response.json()

    print("✅ Authentication successful!")
    print(f"🔑 Token: {token[:20]}...")

    return {
        "token": token,
        "catalog": token_info["token"]["catalog"],
        "user": token_info["token"]["user"]["name"],
        "project": token_info["token"]["project"]["name"],
        "auth_url": auth_url,
    }


# ======================
# NETWORK API (Neutron)
# ======================
def get_network_endpoint(catalog):
    """
    Tìm URL của dịch vụ 'network' (Neutron) từ catalog của token.
    """
    for service in catalog:
        if service["type"] == "network":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":  # public hoặc admin tùy môi trường
                    return endpoint["url"]
    raise Exception("❌ Không tìm thấy network endpoint trong catalog")


# ======================
# LIST NETWORKS
# ======================
def list_networks():
    conn = get_conn()
    token = conn["token"]
    neutron_url = get_network_endpoint(conn["catalog"])

    headers = {"X-Auth-Token": token}
    resp = requests.get(f"{neutron_url}/v2.0/networks", headers=headers)
    resp.raise_for_status()

    networks = resp.json()["networks"]

    result = []
    for net in networks:
        result.append({
            "id": net["id"],
            "name": net.get("name", "(no name)"),
            "status": net.get("status", "UNKNOWN"),
            "external": net.get("router:external", False),
            "subnets": net.get("subnets", [])
        })
    return result


# ======================
# LIST NETWORKS WITH SUBNET DETAILS
# ======================
def list_networks_with_subnets():
    conn = get_conn()
    token = conn["token"]
    neutron_url = get_network_endpoint(conn["catalog"])
    headers = {"X-Auth-Token": token}

    # 🔹 Lấy danh sách network
    nets_resp = requests.get(f"{neutron_url}/v2.0/networks", headers=headers)
    nets_resp.raise_for_status()
    networks = nets_resp.json()["networks"]

    # 🔹 Lấy danh sách subnet
    subs_resp = requests.get(f"{neutron_url}/v2.0/subnets", headers=headers)
    subs_resp.raise_for_status()
    subnets = subs_resp.json()["subnets"]

    subnet_dict = {s["id"]: s for s in subnets}

    result = []
    for net in networks:
        subnet_details = []
        for sid in net.get("subnets", []):
            if sid in subnet_dict:
                sub = subnet_dict[sid]
                subnet_details.append({
                    "id": sub["id"],
                    "name": sub.get("name", "(no name)"),
                    "cidr": sub["cidr"],
                    "gateway_ip": sub.get("gateway_ip")
                })
        result.append({
            "id": net["id"],
            "name": net.get("name", "(no name)"),
            "status": net.get("status", "UNKNOWN"),
            "external": net.get("router:external", False),
            "subnets": subnet_details
        })
    return result

def create_network(name, subnet_name, cidr):
    conn = get_conn()
    token = conn["token"]

    # 🔹 1. Find the Neutron (network) service endpoint from the catalog
    neutron_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "network":
            # You can choose "public" or "internal" depending on your setup
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":  
                    neutron_endpoint = endpoint["url"]
                    break
        if neutron_endpoint:
            break

    if not neutron_endpoint:
        raise Exception("❌ Neutron endpoint not found in service catalog")

    headers = {
        "X-Auth-Token": token,
        "Content-Type": "application/json",
    }

    # 🔹 2. Create the network
    network_url = f"{neutron_endpoint}/v2.0/networks"
    net_payload = {"network": {"name": name, "admin_state_up": True}}

    net_response = requests.post(network_url, json=net_payload, headers=headers)
    if net_response.status_code not in (200, 201):
        raise Exception(f"❌ Failed to create network: {net_response.text}")

    network = net_response.json()["network"]
    network_id = network["id"]
    print(f"✅ Created network: {network['name']} (ID: {network_id})")

    # 🔹 3. Create subnet in that network
    subnet_url = f"{neutron_endpoint}/v2.0/subnets"
    subnet_payload = {
        "subnet": {
            "name": subnet_name,
            "network_id": network_id,
            "ip_version": 4,
            "cidr": cidr,
            "enable_dhcp": True,
        }
    }

    sub_response = requests.post(subnet_url, json=subnet_payload, headers=headers)
    if sub_response.status_code not in (200, 201):
        raise Exception(f"❌ Failed to create subnet: {sub_response.text}")

    subnet = sub_response.json()["subnet"]
    print(f"✅ Created subnet: {subnet['name']} (CIDR: {subnet['cidr']})")

    # 🔹 4. Return both objects
    return {
        "network": network,
        "subnet": subnet,
    }


def delete_network(network_id):
    conn = get_conn()
    token = conn["token"]

    # 🔹 1. Find the Neutron (network) endpoint from the service catalog
    neutron_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "network":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    neutron_endpoint = endpoint["url"]
                    break
        if neutron_endpoint:
            break

    if not neutron_endpoint:
        raise Exception("❌ Neutron endpoint not found in service catalog")

    headers = {
        "X-Auth-Token": token,
        "Content-Type": "application/json"
    }

    # 🔹 2. Send DELETE request to Neutron API
    url = f"{neutron_endpoint}/v2.0/networks/{network_id}"
    response = requests.delete(url, headers=headers)

    if response.status_code not in (204, 202):
        raise Exception(f"❌ Failed to delete network {network_id}: {response.text}")

    print(f"✅ Deleted network ID: {network_id}")
    return True


# ======================
# ROUTER
# ======================
def list_routers():
    conn = get_conn()
    token = conn["token"]

    # 🔹 1. Find Neutron (network) endpoint from the service catalog
    neutron_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "network":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    neutron_endpoint = endpoint["url"]
                    break
        if neutron_endpoint:
            break

    if not neutron_endpoint:
        raise Exception("❌ Neutron endpoint not found in service catalog")

    # 🔹 2. Gửi yêu cầu GET đến API Routers
    url = f"{neutron_endpoint}/v2.0/routers"
    headers = {"X-Auth-Token": token}
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"❌ Failed to list routers: {response.text}")

    routers = response.json().get("routers", [])
    print(f"✅ Found {len(routers)} routers.")
    return routers

def list_external_networks():
    conn = get_conn()
    token = conn["token"]

    # 🔹 1. Find Neutron (network) endpoint from catalog
    neutron_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "network":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    neutron_endpoint = endpoint["url"]
                    break
        if neutron_endpoint:
            break

    if not neutron_endpoint:
        raise Exception("❌ Neutron endpoint not found in catalog")

    # 🔹 2. Query all networks
    url = f"{neutron_endpoint}/v2.0/networks"
    headers = {"X-Auth-Token": token}
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"❌ Failed to list networks: {response.text}")

    # 🔹 3. Filter external networks (router:external=True)
    networks = response.json().get("networks", [])
    external_networks = [net for net in networks if net.get("router:external")]

    print(f"✅ Found {len(external_networks)} external networks.")
    return external_networks

def create_router(name, external_network_id):
    conn = get_conn()
    token = conn["token"]

    # 🔹 1. Find Neutron (network) endpoint from catalog
    neutron_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "network":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    neutron_endpoint = endpoint["url"]
                    break
        if neutron_endpoint:
            break

    if not neutron_endpoint:
        raise Exception("❌ Neutron endpoint not found in catalog")

    # 🔹 2. Define router creation payload
    payload = {
        "router": {
            "name": name,
            "admin_state_up": True,
            "external_gateway_info": {
                "network_id": external_network_id
            }
        }
    }

    headers = {
        "X-Auth-Token": token,
        "Content-Type": "application/json"
    }

    # 🔹 3. Send POST request to create router
    url = f"{neutron_endpoint}/v2.0/routers"
    response = requests.post(url, json=payload, headers=headers)

    if response.status_code not in (201, 202):
        raise Exception(f"❌ Failed to create router: {response.text}")

    router = response.json()["router"]
    print(f"✅ Created router '{router['name']}' (ID: {router['id']})")

    return router

def delete_router(router_id):
    conn = get_conn()
    token = conn["token"]

    # 🔹 1. Find Neutron (network) endpoint from catalog
    neutron_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "network":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    neutron_endpoint = endpoint["url"]
                    break
        if neutron_endpoint:
            break

    if not neutron_endpoint:
        raise Exception("❌ Neutron endpoint not found in catalog")

    # 🔹 2. Send DELETE request
    headers = {"X-Auth-Token": token}
    url = f"{neutron_endpoint}/v2.0/routers/{router_id}"
    res = requests.delete(url, headers=headers)

    # 🔹 3. Check response
    if res.status_code not in (204, 202):
        raise Exception(f"❌ Failed to delete router {router_id}: {res.text}")

    print(f"✅ Deleted router ID: {router_id}")
    return True

# ======================
# INSTANCE
# ======================
def list_servers_detailed():
    conn = get_conn()
    token = conn["token"]

    # 🔹 1. Find Nova (compute) endpoint from service catalog
    nova_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "compute":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    nova_endpoint = endpoint["url"]
                    break
        if nova_endpoint:
            break

    if not nova_endpoint:
        raise Exception("❌ Nova endpoint not found in catalog")

    # 🔹 2. Send GET request for detailed server list
    url = f"{nova_endpoint}/servers/detail"
    headers = {"X-Auth-Token": token}
    res = requests.get(url, headers=headers)

    if res.status_code != 200:
        raise Exception(f"❌ Failed to list servers: {res.text}")

    data = res.json()
    servers = data.get("servers", [])

    # 🔹 3. Return simplified structure
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "status": s["status"],
            "flavor": s["flavor"]["id"],
            "addresses": s.get("addresses", {}),
            "image": s.get("image", {}).get("id"),
        }
        for s in servers
    ]

def list_images():
    conn = get_conn()
    token = conn["token"]

    # 🔹 1. Find Glance (image) endpoint from service catalog
    glance_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "image":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    glance_endpoint = endpoint["url"]
                    break
        if glance_endpoint:
            break

    if not glance_endpoint:
        raise Exception("❌ Glance endpoint not found in catalog")

    # 🔹 2. Send GET request to Glance API to list images
    url = f"{glance_endpoint}/v2/images"
    headers = {"X-Auth-Token": token}
    res = requests.get(url, headers=headers)

    if res.status_code != 200:
        raise Exception(f"❌ Failed to list images: {res.text}")

    data = res.json()
    images = data.get("images", [])

    # 🔹 3. Return simplified list
    return [
        {
            "id": img["id"],
            "name": img.get("name"),
            "status": img.get("status"),
            "disk_format": img.get("disk_format"),
            "size": img.get("size"),
        }
        for img in images
    ]

def list_flavors():
    conn = get_conn()
    token = conn["token"]

    # 🔹 1. Find Nova (compute) endpoint from Keystone catalog
    nova_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "compute":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    nova_endpoint = endpoint["url"]
                    break
        if nova_endpoint:
            break

    if not nova_endpoint:
        raise Exception("❌ Nova endpoint not found in catalog")

    # 🔹 2. Send GET request to list detailed flavors
    url = f"{nova_endpoint}/flavors/detail"
    headers = {"X-Auth-Token": token}
    res = requests.get(url, headers=headers)

    if res.status_code != 200:
        raise Exception(f"❌ Failed to list flavors: {res.text}")

    data = res.json()
    flavors = data.get("flavors", [])

    # 🔹 3. Return simplified info
    return [
        {
            "id": f["id"],
            "name": f.get("name"),
            "vcpus": f.get("vcpus"),
            "ram": f.get("ram"),
            "disk": f.get("disk"),
            "swap": f.get("swap"),
        }
        for f in flavors
    ]

def list_security_groups():
    conn = get_conn()
    token = conn["token"]

    # 🔹 1. Find Neutron (network) endpoint from the Keystone catalog
    neutron_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "network":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    neutron_endpoint = endpoint["url"]
                    break
        if neutron_endpoint:
            break

    if not neutron_endpoint:
        raise Exception("❌ Neutron endpoint not found in catalog")

    # 🔹 2. Send GET request to list all security groups
    url = f"{neutron_endpoint}/v2.0/security-groups"
    headers = {"X-Auth-Token": token}
    res = requests.get(url, headers=headers)

    if res.status_code != 200:
        raise Exception(f"❌ Failed to list security groups: {res.text}")

    # 🔹 3. Parse JSON and extract relevant info
    data = res.json()
    sec_groups = data.get("security_groups", [])

    return [
        {
            "id": sg["id"],
            "name": sg.get("name"),
            "description": sg.get("description"),
            "tenant_id": sg.get("tenant_id"),
            "rules": sg.get("security_group_rules", []),
        }
        for sg in sec_groups
    ]

def list_keypairs():
    conn = get_conn()
    token = conn["token"]

    # 🔹 1. Find Nova (compute) endpoint from Keystone catalog
    nova_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "compute":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    nova_endpoint = endpoint["url"]
                    break
        if nova_endpoint:
            break

    if not nova_endpoint:
        raise Exception("❌ Nova endpoint not found in catalog")

    # 🔹 2. Send GET request to list keypairs
    url = f"{nova_endpoint}/os-keypairs"
    headers = {"X-Auth-Token": token}
    res = requests.get(url, headers=headers)

    if res.status_code != 200:
        raise Exception(f"❌ Failed to list keypairs: {res.text}")

    # 🔹 3. Parse and return simplified keypair info
    keypairs = res.json().get("keypairs", [])
    result = []
    for kp in keypairs:
        kp_data = kp.get("keypair", {})
        result.append({
            "name": kp_data.get("name"),
            "fingerprint": kp_data.get("fingerprint"),
            "public_key": kp_data.get("public_key"),
            "type": kp_data.get("type"),
        })
    return result


def create_instance(name, image, flavor, network_ids, key_name, security_group="nhom07_secgr"):
    conn = get_conn()
    token = conn["token"]

    # 🔹 1️⃣ Find the Nova endpoint from the service catalog
    nova_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "compute":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    nova_endpoint = endpoint["url"]
                    break
        if nova_endpoint:
            break

    if not nova_endpoint:
        raise Exception("❌ Nova endpoint not found in catalog")

    # 🔹 2️⃣ Prepare user-data (Base64-encoded cloud-init script)
    user_data_script = """#!/bin/bash
    apt update -y
    apt install -y apache2 curl
    IP=$(hostname -I | awk '{print $1}')
    echo "<h1>Nhóm 07 - Web server đã khởi động!</h1><h2>Địa chỉ IP: $IP</h2>" > /var/www/html/index.html
    systemctl enable apache2
    systemctl restart apache2
    """
    user_data_encoded = base64.b64encode(user_data_script.encode("utf-8")).decode("utf-8")

    # 🔹 3️⃣ Prepare NICs and Security Groups
    nics = [{"uuid": nid} for nid in network_ids]
    security_groups = [{"name": security_group}] if security_group else []

    # 🔹 4️⃣ Create server payload
    payload = {
        "server": {
            "name": name,
            "imageRef": image,
            "flavorRef": flavor,
            "networks": nics,
            "key_name": key_name,
            "security_groups": security_groups,
            "user_data": user_data_encoded,
        }
    }

    headers = {
        "X-Auth-Token": token,
        "Content-Type": "application/json"
    }

    # 🔹 5️⃣ Send POST request to create the instance
    url = f"{nova_endpoint}/servers"
    res = requests.post(url, json=payload, headers=headers)

    if res.status_code not in (202, 200):
        raise Exception(f"❌ Failed to create instance: {res.text}")

    server = res.json().get("server", {})
    print(f"✅ Instance creation initiated: {server.get('id')} ({name})")
    return server


def delete_instance(server_id):
    conn = get_conn()
    token = conn["token"]

    # 🔹 1️⃣ Find the Nova (compute) endpoint from the catalog
    nova_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "compute":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    nova_endpoint = endpoint["url"]
                    break
        if nova_endpoint:
            break

    if not nova_endpoint:
        raise Exception("❌ Nova endpoint not found in catalog")

    # 🔹 2️⃣ Send DELETE request to Nova API
    url = f"{nova_endpoint}/servers/{server_id}"
    headers = {"X-Auth-Token": token}

    res = requests.delete(url, headers=headers)

    # 🔹 3️⃣ Handle response
    if res.status_code not in (204, 202):
        raise Exception(f"❌ Failed to delete instance {server_id}: {res.text}")

    print(f"🗑️ Deleted instance ID: {server_id}")
    return True

# ======================
# FLOATING IP
# ======================
def assign_floating_ip(instance_id):
    conn = get_conn()
    token = conn["token"]

    # 🔹 1️⃣ Find Neutron endpoint
    neutron_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "network":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    neutron_endpoint = endpoint["url"]
                    break
        if neutron_endpoint:
            break

    if not neutron_endpoint:
        raise Exception("❌ Neutron endpoint not found in catalog")

    headers = {"X-Auth-Token": token, "Content-Type": "application/json"}

    # ======================================================
    # STEP 1️⃣ — Find external network
    # ======================================================
    res = requests.get(f"{neutron_endpoint}/v2.0/networks?router:external=True", headers=headers)
    if res.status_code != 200:
        raise Exception(f"❌ Failed to list networks: {res.text}")

    networks = res.json().get("networks", [])
    if not networks:
        raise Exception("❌ No external network found")

    external_network = networks[0]
    external_net_id = external_network["id"]

    # ======================================================
    # STEP 2️⃣ — Find ports belonging to the instance
    # ======================================================
    res = requests.get(f"{neutron_endpoint}/v2.0/ports?device_id={instance_id}", headers=headers)
    if res.status_code != 200:
        raise Exception(f"❌ Failed to list instance ports: {res.text}")

    ports = res.json().get("ports", [])
    if not ports:
        raise Exception("❌ No ports found for this instance")

    # ======================================================
    # STEP 3️⃣ — Find routers that have external gateway
    # ======================================================
    res = requests.get(f"{neutron_endpoint}/v2.0/routers", headers=headers)
    if res.status_code != 200:
        raise Exception(f"❌ Failed to list routers: {res.text}")

    routers = res.json().get("routers", [])
    valid_internal_networks = set()

    for r in routers:
        gw_info = r.get("external_gateway_info")
        if gw_info and gw_info.get("network_id") == external_net_id:
            # List all router ports (internal interfaces)
            res_ports = requests.get(f"{neutron_endpoint}/v2.0/ports?device_id={r['id']}", headers=headers)
            if res_ports.status_code == 200:
                for p in res_ports.json().get("ports", []):
                    for ip in p.get("fixed_ips", []):
                        subnet_id = ip["subnet_id"]
                        # Fetch subnet details to get its network_id
                        sub_res = requests.get(f"{neutron_endpoint}/v2.0/subnets/{subnet_id}", headers=headers)
                        if sub_res.status_code == 200:
                            subnet = sub_res.json().get("subnet", {})
                            valid_internal_networks.add(subnet["network_id"])

    # ======================================================
    # STEP 4️⃣ — Select a target port
    # ======================================================
    target_port = None
    for port in ports:
        if port["network_id"] in valid_internal_networks:
            target_port = port
            break

    if not target_port:
        raise Exception("❌ No valid port connected to a router with external gateway found")

    # ======================================================
    # STEP 5️⃣ — Find or create a floating IP
    # ======================================================
    project_id = target_port["project_id"]

    res = requests.get(f"{neutron_endpoint}/v2.0/floatingips?project_id={project_id}", headers=headers)
    if res.status_code != 200:
        raise Exception(f"❌ Failed to list floating IPs: {res.text}")

    fips = res.json().get("floatingips", [])
    unused_ips = [ip for ip in fips if ip["status"] == "DOWN" and not ip.get("port_id")]

    if unused_ips:
        floating_ip = unused_ips[0]
    else:
        # Create a new floating IP
        payload = {
            "floatingip": {
                "floating_network_id": external_net_id,
                "project_id": project_id
            }
        }
        res = requests.post(f"{neutron_endpoint}/v2.0/floatingips", headers=headers, json=payload)
        if res.status_code != 201:
            raise Exception(f"❌ Failed to create floating IP: {res.text}")
        floating_ip = res.json()["floatingip"]

    # ======================================================
    # STEP 6️⃣ — Associate floating IP to instance port
    # ======================================================
    payload = {"floatingip": {"port_id": target_port["id"]}}
    res = requests.put(f"{neutron_endpoint}/v2.0/floatingips/{floating_ip['id']}", headers=headers, json=payload)

    if res.status_code != 200:
        raise Exception(f"❌ Failed to associate floating IP: {res.text}")

    ip_address = floating_ip.get("floating_ip_address")
    print(f"✅ Assigned Floating IP {ip_address} to instance {instance_id}")
    return floating_ip

# ======================
# KEYPAIR
# ======================
def list_keypairs():
    conn = get_conn()
    token = conn["token"]

    # 🔹 1️⃣ Find Nova (Compute) endpoint from the catalog
    nova_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "compute":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    nova_endpoint = endpoint["url"]
                    break
        if nova_endpoint:
            break

    if not nova_endpoint:
        raise Exception("❌ Nova endpoint not found in catalog")

    # 🔹 2️⃣ GET request to list keypairs
    url = f"{nova_endpoint}/os-keypairs"
    headers = {"X-Auth-Token": token}

    res = requests.get(url, headers=headers)

    if res.status_code != 200:
        raise Exception(f"❌ Failed to list keypairs: {res.text}")

    data = res.json()

    # 🔹 3️⃣ Parse keypair info
    result = []
    for item in data.get("keypairs", []):
        kp = item.get("keypair", {})
        result.append({
            "name": kp.get("name"),
            "fingerprint": kp.get("fingerprint"),
            "public_key": kp.get("public_key")
        })

    return result


def create_keypair(name):
    conn = get_conn()
    token = conn["token"]

    # 🔹 1️⃣ Find Nova (Compute) endpoint
    nova_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "compute":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    nova_endpoint = endpoint["url"]
                    break
        if nova_endpoint:
            break

    if not nova_endpoint:
        raise Exception("❌ Nova endpoint not found in catalog")

    # 🔹 2️⃣ Prepare request
    url = f"{nova_endpoint}/os-keypairs"
    headers = {
        "X-Auth-Token": token,
        "Content-Type": "application/json"
    }

    payload = {
        "keypair": {
            "name": name
        }
    }

    # 🔹 3️⃣ Send POST request
    res = requests.post(url, json=payload, headers=headers)

    if res.status_code != 200 and res.status_code != 201:
        raise Exception(f"❌ Failed to create keypair '{name}': {res.text}")

    keypair_data = res.json().get("keypair", {})

    print(f"[+] Created Keypair: {keypair_data.get('name')}")
    return keypair_data

import requests

def delete_keypair(name):
    conn = get_conn()
    token = conn["token"]

    # 🔹 1️⃣ Find Nova (Compute) endpoint
    nova_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "compute":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    nova_endpoint = endpoint["url"]
                    break
        if nova_endpoint:
            break

    if not nova_endpoint:
        raise Exception("❌ Nova endpoint not found in catalog")

    # 🔹 2️⃣ Construct DELETE URL
    url = f"{nova_endpoint}/os-keypairs/{name}"

    headers = {
        "X-Auth-Token": token,
        "Content-Type": "application/json"
    }

    # 🔹 3️⃣ Send DELETE request
    res = requests.delete(url, headers=headers)

    if res.status_code not in (202, 204):
        raise Exception(f"❌ Failed to delete keypair '{name}': {res.text}")

    print(f"[-] Deleted keypair: {name}")
    return True




# ======================
# SCALE
# ======================
def scale_up_instances(base_name, image, flavor, network_id, key_name, target_count):
    conn = get_conn()
    token = conn["token"]

    # 🔹 1️⃣ Find Nova (Compute) endpoint
    nova_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "compute":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    nova_endpoint = endpoint["url"]
                    break
        if nova_endpoint:
            break

    if not nova_endpoint:
        raise Exception("❌ Nova endpoint not found in service catalog")

    headers = {"X-Auth-Token": token, "Content-Type": "application/json"}

    # ======================================================
    # STEP 1️⃣ — Get current list of instances
    # ======================================================
    res = requests.get(f"{nova_endpoint}/servers/detail", headers=headers)
    if res.status_code != 200:
        raise Exception(f"❌ Failed to list servers: {res.text}")

    servers = res.json().get("servers", [])
    current_count = len(servers)

    print(f"[Scale-Up] Current instances: {current_count}, Target: {target_count}")

    # ======================================================
    # STEP 2️⃣ — Check if scaling needed
    # ======================================================
    if current_count >= target_count:
        print(f"[=] No scale-up needed (already have {current_count} instances).")
        return True

    to_create = target_count - current_count
    print(f"[+] Need to create {to_create} new instance(s).")

    # ======================================================
    # STEP 3️⃣ — Create new instances
    # ======================================================
    for i in range(to_create):
        name = f"{base_name}_{current_count + i + 1}"
        print(f"[+] Creating instance: {name}")

        # You already have a REST-based create_instance() function — call it directly here
        create_instance(
            name=name,
            image=image,
            flavor=flavor,
            network_ids=[network_id],
            key_name=key_name
        )

    print(f"✅ Successfully scaled up from {current_count} → {target_count} instances.")
    return True


def scale_down_instances(base_name, target_count):
    conn = get_conn()
    token = conn["token"]

    # 🔹 1️⃣ Find Nova (Compute) endpoint
    nova_endpoint = None
    for service in conn["catalog"]:
        if service["type"] == "compute":
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    nova_endpoint = endpoint["url"]
                    break
        if nova_endpoint:
            break

    if not nova_endpoint:
        raise Exception("❌ Nova endpoint not found in service catalog")

    headers = {"X-Auth-Token": token, "Content-Type": "application/json"}

    # ======================================================
    # STEP 1️⃣ — Get all instances
    # ======================================================
    res = requests.get(f"{nova_endpoint}/servers/detail", headers=headers)
    if res.status_code != 200:
        raise Exception(f"❌ Failed to list servers: {res.text}")

    instances = res.json().get("servers", [])
    current_count = len(instances)

    print(f"[Scale-Down] Current instances: {current_count}, Target: {target_count}")

    # ======================================================
    # STEP 2️⃣ — Check if scaling down needed
    # ======================================================
    if current_count <= target_count:
        print(f"[=] No scale-down needed (already have {current_count} instances).")
        return True

    # ======================================================
    # STEP 3️⃣ — Determine how many to delete
    # ======================================================
    to_delete_count = current_count - target_count
    print(f"[-] Need to delete {to_delete_count} instance(s).")

    # Sort instances by created time (newest first)
    instances.sort(key=lambda s: s["created"], reverse=True)

    # Pick newest ones to delete
    to_delete = instances[:to_delete_count]

    # ======================================================
    # STEP 4️⃣ — Delete instances
    # ======================================================
    for s in to_delete:
        server_id = s["id"]
        server_name = s["name"]
        print(f"[-] Deleting {server_name} ({server_id})")

        delete_url = f"{nova_endpoint}/servers/{server_id}"
        del_res = requests.delete(delete_url, headers=headers)

        if del_res.status_code not in (204, 202):
            print(f"⚠️ Failed to delete {server_name}: {del_res.text}")
        else:
            print(f"✅ Deleted {server_name}")

    print(f"✅ Successfully scaled down from {current_count} → {target_count} instances.")
    return True