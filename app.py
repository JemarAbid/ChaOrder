from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import mysql.connector
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import os

load_dotenv()

app = Flask(__name__)
app.secret_key = "chaorder_secret_key_123"   # needed for login sessions

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form['full_name']
        email = request.form['email']
        password = request.form['password']

        hashed_password = generate_password_hash(password)

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            existing = cursor.fetchone()

            if existing:
                cursor.close()
                conn.close()
                return render_template('register.html', error="Email already registered")

            cursor.execute(
                "INSERT INTO users (full_name, email, password) VALUES (%s, %s, %s)",
                (full_name, email, hashed_password)
            )
            conn.commit()
            cursor.close()
            conn.close()

            return render_template('register.html', success="Account created successfully! You can now login.")
        
        except Exception as e:
            return render_template('register.html', error=f"Error: {str(e)}")

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)

            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()

            cursor.close()
            conn.close()

            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['full_name'] = user['full_name']
                session['role'] = user['role']
                return redirect(url_for('home'))
            else:
                return render_template('login.html', error="Invalid email or password")

        except Exception as e:
            return render_template('login.html', error=f"Error: {str(e)}")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/menu')
def menu():
    selected_category = request.args.get('category', 'All')
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT DISTINCT category FROM products WHERE is_available = 'Yes'")
        categories = [row['category'] for row in cursor.fetchall() if row['category']]

        if selected_category and selected_category != 'All':
            cursor.execute("SELECT * FROM products WHERE is_available = 'Yes' AND category = %s", (selected_category,))
        else:
            cursor.execute("SELECT * FROM products WHERE is_available = 'Yes'")

        products = cursor.fetchall()
        cursor.close()
        conn.close()

        return render_template('menu.html', products=products, categories=categories, selected_category=selected_category)
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    if 'cart' not in session:
        session['cart'] = []

    for item in session['cart']:
        if item['product_id'] == product_id:
            item['quantity'] += 1
            session.modified = True
            return redirect(url_for('menu'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, price FROM products WHERE id = %s", (product_id,))
        product = cursor.fetchone()
        cursor.close()
        conn.close()

        if product:
            session['cart'].append({
                'product_id': product['id'],
                'name': product['name'],
                'price': float(product['price']),
                'quantity': 1
            })
            session.modified = True
    except Exception as e:
        print(e)

    return redirect(url_for('menu'))

@app.route('/cart')
def cart():
    cart_items = session.get('cart', [])
    total = sum(item['price'] * item['quantity'] for item in cart_items)
    return render_template('cart.html', cart_items=cart_items, total=total)

@app.route('/place_order', methods=['POST'])
def place_order():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    cart_items = session.get('cart', [])
    if not cart_items:
        return redirect(url_for('cart'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        total = sum(item['price'] * item['quantity'] for item in cart_items)

        cursor.execute(
            "INSERT INTO orders (user_id, total_amount, status) VALUES (%s, %s, %s)",
            (session['user_id'], total, 'Pending')
        )
        order_id = cursor.lastrowid

        for item in cart_items:
            cursor.execute(
                """INSERT INTO order_items 
                   (order_id, product_id, quantity, sugar_level, ice_level, add_ons, price) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    order_id,
                    item['product_id'],
                    item['quantity'],
                    item.get('sugar_level'),
                    item.get('ice_level'),
                    item.get('add_ons'),
                    item['price']
                )
            )

        conn.commit()
        cursor.close()
        conn.close()

        session.pop('cart', None)

        return render_template('order_success.html', order_id=order_id, total=total)

    except Exception as e:
        return f"Error placing order: {str(e)}"

@app.route('/my_orders')
def my_orders():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT * FROM orders 
            WHERE user_id = %s AND is_deleted = FALSE
            ORDER BY created_at DESC
        """, (session['user_id'],))
        orders = cursor.fetchall()

        for order in orders:
            cursor.execute("""
                SELECT oi.quantity, oi.price, oi.sugar_level, oi.ice_level, oi.add_ons, p.name 
                FROM order_items oi
                JOIN products p ON oi.product_id = p.id
                WHERE oi.order_id = %s
            """, (order['id'],))
            order['order_items'] = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('my_orders.html', orders=orders)

    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/admin')
def admin():
    if not session.get('user_id') or session.get('role') not in ['admin', 'staff']:
        return redirect(url_for('home'))

    selected_date = request.args.get('date', '')

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        order_query = """
            SELECT o.id, o.total_amount, o.status, o.created_at, 
                   u.full_name AS customer_name
            FROM orders o
            JOIN users u ON o.user_id = u.id
        """
        
        if selected_date:
            order_query += " WHERE DATE(o.created_at) = %s"
            order_query += " ORDER BY o.created_at DESC"
            cursor.execute(order_query, (selected_date,))
        else:
            order_query += " ORDER BY o.created_at DESC"
            cursor.execute(order_query)

        orders = cursor.fetchall()

        total_orders = len(orders)
        pending_orders = sum(1 for o in orders if o['status'] == 'Pending')
        total_revenue = sum(float(o['total_amount']) for o in orders if o['status'] == 'Completed')

        cursor.execute("""
            SELECT oi.order_id, oi.quantity, oi.price, oi.sugar_level, oi.ice_level, oi.add_ons, p.name
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
        """)
        all_items = cursor.fetchall()

        for order in orders:
            order['order_items'] = [item for item in all_items if item['order_id'] == order['id']]

        cursor.close()
        conn.close()

        return render_template('admin.html', orders=orders, total_orders=total_orders, pending_orders=pending_orders, total_revenue=total_revenue, selected_date=selected_date)

    except Exception as e:
        return f"<h2>Error in Admin</h2><pre>{str(e)}</pre><a href='/'>Back</a>"
    
@app.route('/update_status/<int:order_id>', methods=['POST'])
def update_status(order_id):
    if not session.get('user_id') or session.get('role') not in ['admin', 'staff']:
        return redirect(url_for('home'))

    new_status = request.form.get('status')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET status = %s WHERE id = %s", (new_status, order_id))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(e)

    return redirect(url_for('admin'))

@app.route('/check_session')
def check_session():
    return f"""
    <h2>Current Session</h2>
    <p><strong>User ID:</strong> {session.get('user_id')}</p>
    <p><strong>Full Name:</strong> {session.get('full_name')}</p>
    <p><strong>Role:</strong> {session.get('role')}</p>
    <br>
    <a href="/">Back to Home</a>
    """

@app.route('/admin/products')
def admin_products():
    if not session.get('user_id') or session.get('role') not in ['admin', 'staff']:
        return redirect(url_for('home'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM products ORDER BY id")
        products = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('admin_products.html', products=products)
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/admin/products/delete/<int:product_id>')
def delete_product(product_id):
    if not session.get('user_id') or session.get('role') != 'admin':
        return redirect(url_for('home'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(e)

    return redirect(url_for('admin_products'))

@app.route('/admin/products/add', methods=['GET', 'POST'])
def add_product():
    if not session.get('user_id') or session.get('role') != 'admin':
        return redirect(url_for('home'))

    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        price = request.form['price']
        stock = request.form['stock']
        is_available = request.form['is_available']
        category = request.form['category']

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO products (name, description, price, stock, is_available, category)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (name, description, price, stock, is_available, category))
            conn.commit()
            cursor.close()
            conn.close()
            return redirect(url_for('admin_products'))
        except Exception as e:
            return render_template('admin_add_product.html', error=str(e))

    return render_template('admin_add_product.html')

@app.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    if not session.get('user_id') or session.get('role') != 'admin':
        return redirect(url_for('home'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            name = request.form['name']
            description = request.form['description']
            price = request.form['price']
            stock = request.form['stock']
            is_available = request.form['is_available']
            category = request.form['category']

            cursor.execute("""
                UPDATE products 
                SET name=%s, description=%s, price=%s, stock=%s, is_available=%s, category=%s
                WHERE id=%s
            """, (name, description, price, stock, is_available, category, product_id))
            conn.commit()
            cursor.close()
            conn.close()
            return redirect(url_for('admin_products'))

        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        product = cursor.fetchone()
        cursor.close()
        conn.close()

        if not product:
            return "Product not found"

        return render_template('admin_edit_product.html', product=product)

    except Exception as e:
        return f"Error: {str(e)}"

# ====================== API ROUTES ======================

@app.route('/api/products', methods=['GET'])
def api_get_products():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, description, price, stock, is_available, category FROM products WHERE is_available = 'Yes'")
        products = cursor.fetchall()
        cursor.close()
        conn.close()

        for p in products:
            p['price'] = float(p['price'])

        return jsonify({
            "success": True,
            "products": products
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['GET'])
def api_get_product(product_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, description, price, stock, is_available, category FROM products WHERE id = %s", (product_id,))
        product = cursor.fetchone()
        cursor.close()
        conn.close()

        if not product:
            return jsonify({"success": False, "error": "Product not found"}), 404

        product['price'] = float(product['price'])
        return jsonify({"success": True, "product": product})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/orders', methods=['GET'])
def api_get_orders():
    if not session.get('user_id'):
        return jsonify({"success": False, "error": "Login required"}), 401

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if session.get('role') in ['admin', 'staff']:
            cursor.execute("""
                SELECT o.id, o.total_amount, o.status, o.created_at, u.full_name AS customer_name
                FROM orders o
                JOIN users u ON o.user_id = u.id
                ORDER BY o.created_at DESC
            """)
        else:
            cursor.execute("""
                SELECT id, total_amount, status, created_at
                FROM orders
                WHERE user_id = %s
                ORDER BY created_at DESC
            """, (session['user_id'],))

        orders = cursor.fetchall()

        for order in orders:
            order['total_amount'] = float(order['total_amount'])
            order['created_at'] = str(order['created_at'])

        cursor.close()
        conn.close()

        return jsonify({
            "success": True,
            "orders": orders
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/orders/<int:order_id>/status', methods=['PUT'])
def api_update_order_status(order_id):
    if not session.get('user_id') or session.get('role') not in ['admin', 'staff']:
        return jsonify({"success": False, "error": "Admin or staff access required"}), 403

    data = request.get_json()
    new_status = data.get('status') if data else None

    if not new_status:
        return jsonify({"success": False, "error": "Status is required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET status = %s WHERE id = %s", (new_status, order_id))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "success": True,
            "message": f"Order #{order_id} status updated to {new_status}"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/remove_from_cart/<int:product_id>')
def remove_from_cart(product_id):
    cart = session.get('cart', [])
    new_cart = [item for item in cart if item['product_id'] != product_id]
    session['cart'] = new_cart
    session.modified = True
    return redirect(url_for('cart'))

@app.route('/customize/<int:product_id>', methods=['GET', 'POST'])
def customize(product_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM products WHERE id = %s AND is_available = 'Yes'", (product_id,))
        product = cursor.fetchone()
        cursor.close()
        conn.close()

        if not product:
            return "Product not found", 404

        if request.method == 'POST':
            sugar = request.form.get('sugar_level')
            ice = request.form.get('ice_level')
            add_ons = request.form.get('add_ons')

            extra = 0
            if add_ons in ['Pearls', 'Pudding', 'Crystal Jelly']:
                extra = 15
            elif add_ons == 'Cream Cheese':
                extra = 20

            if 'cart' not in session:
                session['cart'] = []

            session['cart'].append({
                'product_id': product['id'],
                'name': product['name'],
                'price': float(product['price']) + extra,
                'quantity': 1,
                'sugar_level': sugar,
                'ice_level': ice,
                'add_ons': add_ons
            })
            session.modified = True

            return redirect(url_for('cart'))

        return render_template('customize.html', product=product)

    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/delete_order/<int:order_id>')
def delete_order(order_id):
    if not session.get('user_id'):
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET is_deleted = TRUE WHERE id = %s AND user_id = %s AND status IN ('Completed', 'Cancelled')", 
            (order_id, session['user_id'])
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(e)

    return redirect(url_for('my_orders'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            full_name = request.form['full_name']
            password = request.form['password']

            if password:
                hashed_password = generate_password_hash(password)
                cursor.execute(
                    "UPDATE users SET full_name = %s, password = %s WHERE id = %s",
                    (full_name, hashed_password, session['user_id'])
                )
            else:
                cursor.execute(
                    "UPDATE users SET full_name = %s WHERE id = %s",
                    (full_name, session['user_id'])
                )
            
            conn.commit()
            session['full_name'] = full_name  
            success_msg = "Profile updated successfully!"
        else:
            success_msg = None

        cursor.execute("SELECT full_name, email FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()

        return render_template('profile.html', user=user, success=success_msg)

    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True)