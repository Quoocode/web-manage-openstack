from openstack import connection, exceptions
import base64
import os

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
        subnet_details = []
        for sid in getattr(net, "subnet_ids", []):
            try:
                sub = conn.network.get_subnet(sid)
                subnet_details.append(sub)
            except exceptions.NotFoundException:
                continue
        networks.append({
            "id": net.id,
            "name": net.name,
            "subnet_details": subnet_details  
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


def create_instance(name, image, flavor, network_ids, key_name, security_group="nhom07_secgr"):
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
        security_groups=[{"name": security_group}],
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
# KEYPAIR
# ======================
def list_keypairs():
    conn = get_conn()
    keypairs = conn.compute.keypairs()
    result = []
    for kp in keypairs:
        result.append({
            "name": kp.name,
            "fingerprint": kp.fingerprint,
            "public_key": kp.public_key
        })
    return result


def create_keypair(name):
    conn = get_conn()
    keypair = conn.compute.create_keypair(name=name)
    print(f"[+] Created Keypair: {keypair.name}")
    return keypair

def delete_keypair(name):
    conn = get_conn()
    conn.compute.delete_keypair(name, ignore_missing=True)
    print(f"[-] Deleted keypair: {name}")



# ======================
# SCALE
# ======================
def scale_up_instances(base_name, image, flavor, network_id, key_name, target_count):
    conn = get_conn()

    # Đếm tổng số máy hiện có trong hệ thống
    all_instances = list(conn.compute.servers(details=True))
    current_count = len(all_instances)

    print(f"[Scale-Up] Current instances: {current_count}, Target: {target_count}")

    # Nếu đã đạt hoặc vượt target → không cần tạo thêm
    if current_count >= target_count:
        print(f"[=] No scale-up needed (already have {current_count} instances).")
        return True

    # Số máy cần tạo thêm
    to_create = target_count - current_count
    print(f"[+] Need to create {to_create} new instance(s).")

    for i in range(to_create):
        name = f"{base_name}_{current_count + i + 1}"
        print(f"[+] Creating instance: {name}")
        create_instance(name, image, flavor, [network_id], key_name)

    print(f"✅ Successfully scaled up from {current_count} → {target_count} instances.")
    return True


def scale_down_instances(base_name, target_count):
    conn = get_conn()

    # Lấy toàn bộ instance trong hệ thống
    instances = list(conn.compute.servers(details=True))
    current_count = len(instances)

    print(f"[Scale-Down] Current instances: {current_count}, Target: {target_count}")

    # Nếu số lượng hiện tại đã <= target_count thì không cần giảm
    if current_count <= target_count:
        print(f"[=] No scale-down needed (already have {current_count} instances).")
        return True

    # Tính số máy cần xóa
    to_delete_count = current_count - target_count
    print(f"[-] Need to delete {to_delete_count} instance(s).")

    # Sắp xếp theo thời gian tạo (mới nhất trước)
    instances.sort(key=lambda s: s.created_at, reverse=True)

    # Chọn ra các máy mới nhất để xóa
    to_delete = instances[:to_delete_count]

    for s in to_delete:
        print(f"[-] Deleting {s.name}")
        conn.compute.delete_server(s.id, ignore_missing=True)

    print(f"✅ Successfully scaled down from {current_count} → {target_count} instances.")
    return True