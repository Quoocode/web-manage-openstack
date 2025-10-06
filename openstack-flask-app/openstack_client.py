from openstack import connection, exceptions
import base64

def get_conn():
    return connection.Connection(cloud='mycloud')

# ======================
# NETWORK
# ======================
def list_networks():
    conn = get_conn()
    return list(conn.network.networks())

def list_networks_with_subnets():
    conn = get_conn()
    networks = []
    for net in conn.network.networks():
        subnets = []
        for sid in net.subnet_ids:
            try:
                sub = conn.network.get_subnet(sid)
                subnets.append(sub)
            except exceptions.NotFoundException:
                continue
        networks.append({
            "id": net.id,
            "name": net.name,
            "subnets": subnets
        })
    return networks

def create_network(name, subnet_name, cidr):
    conn = get_conn()
    network = conn.network.create_network(name=name)
    conn.network.create_subnet(
        name=subnet_name,
        network_id=network.id,
        ip_version=4,
        cidr=cidr
    )
    return network

def delete_network(network_id):
    conn = get_conn()
    conn.network.delete_network(network_id, ignore_missing=True)

# ======================
# ROUTER
# ======================
def list_routers():
    conn = get_conn()
    return list(conn.network.routers())

def list_external_networks():
    conn = get_conn()
    return [n for n in conn.network.networks() if n.is_router_external]

def create_router(name, external_network_id):
    conn = get_conn()
    return conn.network.create_router(
        name=name,
        external_gateway_info={"network_id": external_network_id}
    )

def delete_router(router_id):
    conn = get_conn()
    conn.network.delete_router(router_id, ignore_missing=True)

# ======================
# INSTANCE
# ======================
def list_servers_detailed():
    conn = get_conn()
    return list(conn.compute.servers(details=True))

def list_images():
    conn = get_conn()
    return list(conn.compute.images())

def list_flavors():
    conn = get_conn()
    return list(conn.compute.flavors())

def list_security_groups():
    conn = get_conn()
    return list(conn.network.security_groups())

def list_keypairs():
    conn = get_conn()
    return list(conn.compute.keypairs())


def create_instance(name, image, flavor, network_ids, key_name, security_group=None):
    conn = get_conn()
    nics = [{"uuid": nid} for nid in network_ids]

    user_data_script = """#!/bin/bash
    apt update -y
    apt install -y apache2 curl
    IP=$(hostname -I | awk '{print $1}')
    echo "<h1>Nhóm 07 - Web server đã khởi động!</h1><h2>Địa chỉ IP: $IP</h2>" > /var/www/html/index.html
    systemctl enable apache2
    systemctl restart apache2
    """
    user_data_encoded = base64.b64encode(user_data_script.encode("utf-8")).decode("utf-8")

    server = conn.compute.create_server(
        name=name,
        image_id=image,
        flavor_id=flavor,
        networks=nics,
        key_name=key_name,
        security_groups=[{"name": security_group}] if security_group else None,
        user_data=user_data_encoded
    )
    conn.compute.wait_for_server(server)
    return server


def delete_instance(server_id):
    conn = get_conn()
    conn.compute.delete_server(server_id, ignore_missing=True)

# ======================
# FLOATING IP
# ======================
def assign_floating_ip(instance_id):
    conn = get_conn()

    # 🔎 1. Tìm external network (router:external=True)
    external_network = None
    for net in conn.network.networks():
        if getattr(net, "is_router_external", False):  # <-- đổi chỗ này
            external_network = net
            break
    if not external_network:
        raise Exception("❌ Không tìm thấy External Network nào")


    # 🔎 2. Lấy tất cả port của instance
    ports = list(conn.network.ports(device_id=instance_id))
    if not ports:
        raise Exception("❌ Không tìm thấy port nào của instance để gán Floating IP")

    # 🔎 3. Chọn port nội bộ nào nối với router có gateway ra external
    target_port = None
    routers = list(conn.network.routers())
    valid_internal_networks = set()

    for r in routers:
        if r.external_gateway_info:  # router có nối external
            # lấy tất cả interface của router (các port nội bộ)
            int_ports = conn.network.ports(device_id=r.id)
            for p in int_ports:
                for ip in p.fixed_ips:
                    subnet = conn.network.get_subnet(ip['subnet_id'])
                    valid_internal_networks.add(subnet.network_id)

    # kiểm tra port của instance có thuộc mạng hợp lệ không
    for port in ports:
        if port.network_id in valid_internal_networks:
            target_port = port
            break

    if not target_port:
        raise Exception("❌ Không tìm thấy port nào của instance nối với Router ra ngoài")

    # 🔎 4. Tìm Floating IP chưa dùng hoặc tạo mới
    unused_ips = [
        ip for ip in conn.network.ips(project_id=target_port.project_id)
        if ip.status == "DOWN" and not ip.port_id
    ]

    if unused_ips:
        floating_ip = unused_ips[0]
    else:
        floating_ip = conn.network.create_ip(
            floating_network_id=external_network.id,
            project_id=target_port.project_id
        )

    if not floating_ip:
        raise Exception("❌ Tạo hoặc lấy Floating IP thất bại")

    # 🔎 5. Gán IP vào port
    conn.network.update_ip(floating_ip, port_id=target_port.id)
    print(f"✅ Gán Floating IP {floating_ip.floating_ip_address} cho instance {instance_id}")
    return floating_ip



# ======================
# SCALE
# ======================
def scale_instances(base_name, image, flavor, network_id, key_name, count):
    conn = get_conn()
    for i in range(count):
        name = f"{base_name}_{i+1}"
        create_instance(name, image, flavor, [network_id], key_name)
    return True

# ======================
# LOAD BALANCER
# ======================
def list_load_balancers():
    conn = get_conn()
    try:
        return list(conn.load_balancer.load_balancers())
    except Exception:
        return []
