from flask import Flask, render_template, request, redirect, url_for, flash
import asyncio
import openstack_client as osc

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
        base_name = request.form['base_name']
        image = request.form['image']
        flavor = request.form['flavor']
        network_id = request.form['network_id']
        key_name = request.form['key_name']
        count = int(request.form['count'])
        await asyncio.to_thread(
            osc.scale_instances,
            base_name, image, flavor, network_id, key_name, count
        )
        flash("⚙️ Scaling complete!", "success")
        return redirect(url_for('instances'))

    images, flavors, networks, keypairs = await asyncio.gather(
        asyncio.to_thread(osc.list_images),
        asyncio.to_thread(osc.list_flavors),
        asyncio.to_thread(osc.list_networks),
        asyncio.to_thread(osc.list_keypairs)
    )
    return render_template('scale.html', images=images, flavors=flavors, networks=networks, keypairs=keypairs)


# ======================
# LOAD BALANCER (ASYNC)
# ======================
@app.route('/loadbalancer')
async def loadbalancer():
    lbs = await asyncio.to_thread(osc.list_load_balancers)
    return render_template('loadbalancer.html', loadbalancers=lbs)


if __name__ == '__main__':
    app.run(debug=True)
