from flask import Flask, render_template, request, redirect, url_for, flash
import asyncio
import openstack_client as osc
from flask import send_file
from flask import session
import os

app = Flask(__name__)
app.secret_key = "supersecret"

@app.route('/')
def home():
    return redirect(url_for('networks'))

# ======================
# NETWORK (ASYNC)
# ======================
@app.route('/networks')
async def networks():
    nets = await asyncio.to_thread(osc.list_networks_with_subnets)
    return render_template('networks.html', networks=nets)


@app.route('/create-network', methods=['POST'])
async def create_network():
    name = request.form['name']
    subnet_name = request.form['subnet_name']
    cidr = request.form['cidr']
    await asyncio.to_thread(osc.create_network, name, subnet_name, cidr)
    flash("✅ Network created successfully!", "success")
    return redirect(url_for('networks'))


@app.route('/delete-network/<id>')
async def delete_network(id):
    await asyncio.to_thread(osc.delete_network, id)
    flash("🗑️ Network deleted!", "warning")
    return redirect(url_for('networks'))


# ======================
# ROUTER (ASYNC)
# ======================
@app.route('/routers')
async def routers():
    routers, external_nets = await asyncio.gather(
        asyncio.to_thread(osc.list_routers),
        asyncio.to_thread(osc.list_external_networks)
    )
    return render_template('routers.html', routers=routers, external_networks=external_nets)


@app.route('/create-router', methods=['POST'])
async def create_router():
    name = request.form['name']
    external_net_id = request.form['external_network_id']
    await asyncio.to_thread(osc.create_router, name, external_net_id)
    flash("🚀 Router created successfully!", "success")
    return redirect(url_for('routers'))


@app.route('/delete-router/<id>')
async def delete_router(id):
    await asyncio.to_thread(osc.delete_router, id)
    flash("🗑️ Router deleted!", "warning")
    return redirect(url_for('routers'))


# ======================
# INSTANCE (ASYNC)
# ======================
@app.route('/instances')
async def instances():
    instances, images, flavors, networks, security_groups, keypairs = await asyncio.gather(
        asyncio.to_thread(osc.list_servers_detailed),
        asyncio.to_thread(osc.list_images),
        asyncio.to_thread(osc.list_flavors),
        asyncio.to_thread(osc.list_networks),
        asyncio.to_thread(osc.list_security_groups),
        asyncio.to_thread(osc.list_keypairs)
    )
    return render_template(
        'instances.html',
        instances=instances,
        images=images,
        flavors=flavors,
        networks=networks,
        security_groups=security_groups,
        keypairs=keypairs
    )


@app.route('/create-instance', methods=['POST'])
async def create_instance():
    name = request.form['name']
    image = request.form['image']
    flavor = request.form['flavor']
    network_ids = request.form.getlist('network_ids')
    security_group = request.form['security_group']
    key_name = request.form['key_name']

    await asyncio.to_thread(
        osc.create_instance,
        name, image, flavor, network_ids, key_name, security_group
    )
    flash("✅ Instance created successfully!", "success")
    return redirect(url_for('instances'))


@app.route('/delete-instance/<id>')
async def delete_instance(id):
    await asyncio.to_thread(osc.delete_instance, id)
    flash("🗑️ Instance deleted!", "warning")
    return redirect(url_for('instances'))


# ======================
# FLOATING IP (NEW)
# ======================
@app.route('/assign-floating-ip/<instance_id>', methods=['POST'])
async def assign_floating_ip(instance_id):
    try:
        await asyncio.to_thread(osc.assign_floating_ip, instance_id)
        flash("🌐 Floating IP assigned successfully!", "success")
    except Exception as e:
        flash(f"⚠️ Failed to assign Floating IP: {e}", "danger")
    return redirect(url_for('instances'))


# ======================
# SCALE (ASYNC)
# ======================
@app.route('/scale', methods=['GET', 'POST'])
async def scale():
    if request.method == 'POST':
        action = request.form.get('action')  # phân biệt scale_up / scale_down

        if action == 'scale_up':
            base_name = request.form['base_name'].strip()
            image = request.form['image'].strip()
            flavor = request.form['flavor'].strip()
            network_id = request.form['network_id'].strip()
            key_name = request.form['key_name'].strip()
            count = int(request.form['target_count'])

            try:
                await asyncio.to_thread(
                    osc.scale_instances,
                    base_name, image, flavor, network_id, key_name, count
                )
                flash(f"✅ Scaled UP {base_name} to {count} instance(s) successfully!", "success")
            except Exception as e:
                flash(f"⚠️ Failed to scale up: {str(e)}", "danger")

        elif action == 'scale_down':
            base_name = request.form['base_name'].strip()
            delete_count = int(request.form['delete_count'])

            try:
                await asyncio.to_thread(
                    osc.delete_instances,  # function bạn sẽ thêm trong openstack_client.py
                    base_name, delete_count
                )
                flash(f"🗑️ Deleted {delete_count} instance(s) for prefix {base_name}.", "warning")
            except Exception as e:
                flash(f"⚠️ Failed to scale down: {str(e)}", "danger")

        return redirect(url_for('instances'))

    # Nếu GET, hiển thị form và load danh sách thông tin
    images = await asyncio.to_thread(osc.list_images)
    flavors = await asyncio.to_thread(osc.list_flavors)
    networks = await asyncio.to_thread(osc.list_networks)
    keypairs = await asyncio.to_thread(osc.list_keypairs)

    return render_template(
        'scale.html',
        images=images,
        flavors=flavors,
        networks=networks,
        keypairs=keypairs
    )
# ======================
# KEYPAIR MANAGEMENT (ASYNC)
# ======================

@app.route('/keypair', methods=['GET'])
async def keypair():
    """Display all keypairs"""
    keypairs = await asyncio.to_thread(osc.list_keypairs)
    return render_template('keypair.html', keypairs=keypairs)

@app.route('/create-keypair', methods=['POST'])
async def create_keypair():
    key_name = request.form['key_name'].strip()

    try:
        keypair = await asyncio.to_thread(osc.create_keypair, key_name)

        # Write private key to temporary file
        file_path = f"/tmp/{key_name}.pem"
        with open(file_path, "w") as f:
            f.write(keypair.private_key)
        os.chmod(file_path, 0o600)

        # Save filename in session for download
        session['download_key_file'] = file_path
        session['download_key_name'] = key_name

        flash(f"✅ Keypair '{key_name}' created successfully! Click the download button below.", "success")
        return redirect(url_for('keypair'))

    except Exception as e:
        flash(f"⚠️ Failed to create keypair: {str(e)}", "danger")
        return redirect(url_for('keypair'))

@app.route('/download-keypair')
async def download_keypair():
    file_path = session.get('download_key_file')
    key_name = session.get('download_key_name')

    # If the file no longer exists, clear session + notify user
    if not file_path or not os.path.exists(file_path):
        session.pop('download_key_file', None)
        session.pop('download_key_name', None)
        flash("⚠️ Keypair file not found or already deleted.", "warning")
        return redirect(url_for('keypair'))

    # Send file and clean up
    response = await asyncio.to_thread(send_file, file_path, as_attachment=True)
    os.remove(file_path)
    session.pop('download_key_file', None)
    session.pop('download_key_name', None)
    return response

@app.route('/delete-keypair/<name>', methods=['POST'])
async def delete_keypair(name):
    try:
        await asyncio.to_thread(osc.delete_keypair, name)
        flash(f"🗑️ Keypair '{name}' deleted successfully!", "success")

        # ✅ Remove download info if this keypair was the one downloaded
        if session.get('download_key_name') == name:
            session.pop('download_key_file', None)
            session.pop('download_key_name', None)

    except Exception as e:
        flash(f"⚠️ Failed to delete keypair: {str(e)}", "danger")

    return redirect(url_for('keypair'))



if __name__ == '__main__':
    app.run(debug=True)
