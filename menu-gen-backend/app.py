from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, redirect, url_for, render_template
from flask_cors import CORS
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import os
import traceback
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
import json
import jwt
from datetime import datetime, timedelta
import uuid

load_dotenv()
MONGO_URI = os.getenv('MONGO_URI')
client = MongoClient(MONGO_URI)
db = client.menu_gen
collection = db.menus
users_collection = db.users

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = "./menu-gen-frontend/uploads"
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['FRONTEND_URL'] = 'http://localhost:5173'
app.config['SECRET_KEY'] = 'thisissecret'

def generate_pdf(food_items, upload_folder):
    pdf_filename = 'menu.pdf'
    pdf_path = os.path.join(upload_folder, pdf_filename)
    c = canvas.Canvas(pdf_path, pagesize=letter)

    c.drawString(100, 750, 'Menu')
    y_position = 700

    for item in food_items:
        c.drawString(100, y_position, f"Item: {item['title']}")
        c.drawString(100, y_position - 20, f"Description: {item['description']}")
        c.drawString(100, y_position - 40, f"Price: {item['price']}")
        if 'picture' in item:
            picture_path = os.path.join(upload_folder, item['picture'])
            print(f"Debug: Full image path: {picture_path}")
            try:
                picture = ImageReader(picture_path)
                c.drawImage(picture, 100, y_position - 240, width=200, height=200, preserveAspectRatio=True, mask='auto')
                y_position -= 280  # Adjust space for image
            except Exception as e:
                print(f"Error loading image {picture_path}: {e}")
                traceback.print_exc()
        else:
            y_position -= 60  # Adjust space for text only

        # Check for end of page and create a new page if necessary
        if y_position <= 100:
            c.showPage()
            y_position = 750

    c.save()
    return pdf_filename

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'x-access-token' in request.headers:
            token = request.headers['x-access-token']
        if not token:
            return jsonify({'message' : 'Token is missing'}), 401
        print(token)
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            #do this with pymongo
            u = users_collection.find_one({'public_id': data['public_id']})
            if u:
                current_user = json.dumps(u, default=str)
            else:
                raise Exception()
        except Exception as e:
            print(e)
            return jsonify({
                'message' : 'Token is invalid.'
            }), 401
        # returns the current logged in users context to the routes
        return  f(current_user, *args, **kwargs)
  
    return decorated

@app.route('/register', methods=['POST'])
def register():
    data = request.form
    print(data)
    
    firstName, lastName, email, password = data.get('firstName'), data.get('lastName'), data.get('email'), data.get('password')
    if not firstName or not lastName or not email or not password:
        return jsonify({'message': 'Missing data!'}), 400
    u = users_collection.insert_one({
        'firstName': firstName,
        'lastName': lastName,
        'email': email,
        'password': password,
        'public_id': str(uuid.uuid4())
    })
    token = jwt.encode({
            'public_id': u['public_id'],
            'exp': datetime.utcnow() + timedelta(minutes=30)
        }, app.config['SECRET_KEY'])
    return jsonify({'token': token.decode('UTF-8')})

@app.route('/login', methods =['POST'])
def login():
    data = request.form
    email, password = data.get('email'), data.get('password')
    if not email or not password:
        return jsonify({'message': 'Missing data!'}), 400
    u = users_collection.find_one({'email': email, 'password': password})
    if not u:
        return jsonify({'message': 'SUCCESS'}), 404
    if u['password'] == password:
        token = jwt.encode({
            'public_id': u['public_id'],
            'exp': datetime.utcnow() + timedelta(minutes=30)
        }, app.config['SECRET_KEY'])
        return jsonify({'token': token})
    return jsonify({'message': 'Invalid credentials!'}), 401

@app.route('/submit', methods=['POST'])
@token_required
def submit_form(current_user):
    restaurant_name = request.form.get('restaurantName')
    restaurant_slogan = request.form.get('restaurantSlogan')
    restaurant_logo = request.files.get('restaurantLogo')
    logo_url = None
    if restaurant_logo:
        logo_filename = secure_filename(restaurant_logo.filename)
        logo_path = os.path.join(app.config['UPLOAD_FOLDER'], logo_filename)
        restaurant_logo.save(logo_path)
        logo_url = f"{app.config['FRONTEND_URL']}/uploads/{logo_filename}"

    food_items = []
    index = 0
    while True:
        title = request.form.get(f'foodItems[{index}].title')
        if not title:
            break
        description = request.form.get(f'foodItems[{index}].description')
        price = request.form.get(f'foodItems[{index}].price')
        dietary_restrictions = request.form.get(f'foodItems[{index}].dietaryRestrictions')
        vegetarian = request.form.get(f'foodItems[{index}].vegetarian') == 'true'
        spicy = request.form.get(f'foodItems[{index}].spicy') == 'true'
        gluten_free = request.form.get(f'foodItems[{index}].glutenFree') == 'true'
        picture = request.files.get(f'foodItems[{index}].picture')
        picture_url = None

        picture_filename = ''
        picture_path = ''
        picture_url = ''

        if picture:
            picture_filename = secure_filename(picture.filename)
            picture_path = os.path.join(app.config['UPLOAD_FOLDER'], picture_filename)
            picture.save(picture_path)
            picture_url = f"{app.config['FRONTEND_URL']}/uploads/{picture_filename}"

        item_data = {
            'title': title,
            'description': description,
            'price': price,
            'dietary_restrictions': dietary_restrictions,
            'vegetarian': vegetarian,
            'spicy': spicy,
            'gluten_free': gluten_free,
            'picture_url': picture_url,
            'picture_path': picture_path
        }

        food_items.append(item_data)
        index += 1
    user_json = json.loads(current_user)
    response = {
        'restaurant_name': restaurant_name,
        'restaurant_slogan': restaurant_slogan,
        'restaurant_logo_url': logo_url,
        'restaurant_logo_path': logo_path,
        'owner': ObjectId(user_json['_id']),
        'food_items': food_items
    }
    insert = collection.insert_one(response)
    return jsonify({'id': str(insert.inserted_id)})

@app.route('/menu/<id>')
def get_menu(id):
    menu = collection.find_one({'_id': ObjectId(id)})
    menu = json.dumps(menu, default=str)
    return menu

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.run(debug=True, port=5002)