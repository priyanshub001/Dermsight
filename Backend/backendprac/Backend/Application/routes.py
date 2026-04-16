from flask import Blueprint, request, jsonify
from extensions import mongo, bcrypt
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from datetime import datetime
from bson import ObjectId
from tensorflow.keras.models import load_model
import base64
import numpy as np
from PIL import Image
import io

model = load_model("skin_model.h5")
main = Blueprint('main', __name__)

# ---------------- REGISTER ----------------
@main.route('/register', methods=['POST'])
def register():
    data = request.json

    if mongo.db.users.find_one({"email": data['email']}):
        return jsonify({"msg": "User already exists"}), 400

    hashed_pw = bcrypt.generate_password_hash(data['password']).decode('utf-8')

    mongo.db.users.insert_one({
        "name": data['name'],
        "email": data['email'],
        "age": data['age'],
        "password": hashed_pw
    })

    return jsonify({"msg": "User registered"})


# ---------------- LOGIN ----------------
@main.route('/login', methods=['POST'])
def login():
    data = request.json
    user = mongo.db.users.find_one({"email": data['email']})

    if user and bcrypt.check_password_hash(user['password'], data['password']):
        token = create_access_token(identity=str(user['_id']))
        return jsonify({"token": token})

    return jsonify({"msg": "Invalid credentials"}), 401

#----------google login---------------
@main.route('/google-login', methods=['POST'])
def google_login():
    data = request.json

    email = data.get("email")
    name = data.get("name")

    if not email:
        return jsonify({"msg": "Email required"}), 400

    # Check if user exists
    user = mongo.db.users.find_one({"email": email})

    if not user:
        #  Create new user (NO PASSWORD)
        new_user = {
            "name": name,
            "email": email,
            "age": None,
            "password": None,  
            "provider": "google"
        }

        result = mongo.db.users.insert_one(new_user)
        user_id = str(result.inserted_id)

    else:
        user_id = str(user["_id"])

    # Create JWT token
    token = create_access_token(identity=user_id)

    return jsonify({
        "token": token,
        "msg": "Google login success"
    })


# ---------------- ANALYZE ----------------
@main.route('/analyze-combined', methods=['POST'])
@jwt_required()
def analyze_combined():

    #  GET DATA
    text = request.form.get("text", "").lower()

    if 'image' not in request.files:
        return jsonify({"error": "Image required"}), 400

    file = request.files['image']

    try:
        # IMAGE PREDICTION
        image = Image.open(file).convert("RGB")
        image = image.resize((224, 224))

        image = np.array(image) / 255.0
        image = np.expand_dims(image, axis=0)

        img_pred = model.predict(image)
        img_index = int(np.argmax(img_pred))
        img_conf = float(np.max(img_pred))

        classes = [
            "Acne", "Eczema", "Melanoma",
            "Psoriasis", "Rosacea", "Normal",
            "Dermatitis", "Fungal Infection", "Warts"
        ]

        img_result = classes[img_index]

        # =========================
        #  TEXT PREDICTION (RULE BASED)
        # =========================
        text_conditions = {
            "Acne": ["pimple", "acne", "oil"],
            "Eczema": ["itch", "dry", "rash", "red"],
            "Infection": ["pain", "pus", "swelling"],
            "Allergy": ["allergy", "reaction"],
        }

        text_result = "Unknown"

        for condition, keywords in text_conditions.items():
            if any(word in text for word in keywords):
                text_result = condition
                break

        # =========================
        #  FINAL DECISION LOGIC
        # =========================
        final_result = img_result
        final_conf = img_conf

        if text_result != "Unknown":

            # ✔ MATCH
            if text_result == img_result:
                final_conf = min(img_conf + 0.1, 0.99)

            #  MISMATCH
            else:
                if img_conf < 0.6:
                    final_result = text_result
                    final_conf = 0.7

        # =========================
        # LOW CONFIDENCE CASE
        # =========================
        if final_conf < 0.5:
            return jsonify({
                "prediction": "Uncertain",
                "confidence": round(final_conf, 2),
                "image_prediction": img_result,
                "text_prediction": text_result
            })

        # =========================
        #  FINAL RESPONSE
        # =========================
        return jsonify({
            "prediction": final_result,
            "confidence": round(final_conf, 2),
            "image_prediction": img_result,
            "text_prediction": text_result
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------- SAVE SCAN ----------------
@main.route('/save-scan', methods=['POST'])
@jwt_required()
def save_scan():

    user_id = get_jwt_identity()
    data = request.json

    mongo.db.scans.insert_one({
        "user_id": user_id,
        "text": data.get("text"),
        "image": data.get("image"),  
        "prediction": data.get("prediction"),
        "confidence": data.get("confidence"),
        "image_prediction": data.get("image_prediction"),
        "text_prediction": data.get("text_prediction"),
        "date": datetime.utcnow()
    })

    return jsonify({"msg": "Scan saved successfully"})

# ---------------- HISTORY ----------------
@main.route('/history', methods=['GET'])
@jwt_required()
def history():

    user_id = get_jwt_identity()

    scans = list(mongo.db.scans.find(
        {"user_id": user_id},
        {
            "_id": 0,
            "text": 1,
            "image": 1,  
            "prediction": 1,
            "confidence": 1,
            "date": 1
        }
    ).sort("date", -1))

    return jsonify(scans)


# ---------------- PROFILE ----------------
@main.route('/profile', methods=['GET'])
@jwt_required()
def profile():
    user_id = get_jwt_identity()

    user = mongo.db.users.find_one(
        {"_id": ObjectId(user_id)},
        {"password": 0}
    )

    if not user:
        return jsonify({"msg": "User not found"}), 404

    user['_id'] = str(user['_id'])

    return jsonify(user)


# ---------------- UPDATE PROFILE ----------------
@main.route('/update-profile', methods=['PUT'])
@jwt_required()
def update_profile():
    user_id = get_jwt_identity()
    data = request.json

    update_data = {}

    if data.get("name"):
        update_data["name"] = data.get("name")

    # 🔹 EMAIL
    if data.get("email"):
        update_data["email"] = data.get("email")

    # 🔹 AGE
    if data.get("age"):
        update_data["age"] = data.get("age")

    # 🔹 PASSWORD (OPTIONAL)
    if data.get("password"):
        hashed_pw = bcrypt.generate_password_hash(
            data.get("password")
        ).decode('utf-8')

        update_data["password"] = hashed_pw

    # UPDATE DATABASE
    mongo.db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": update_data}
    )

    return jsonify({"msg": "Profile updated"})

#----------for text---------------

@main.route('/analyze-text', methods=['POST'])
@jwt_required()
def analyze_text():

    data = request.json
    text = data.get("text", "").lower()

    if not text:
        return jsonify({"error": "Text is required"}), 400

    # KEYWORDS MAP
    conditions = {
        "Acne": ["pimple", "acne", "whitehead", "blackhead", "oil"],
        "Eczema": ["itch", "itching", "dry", "rash", "red", "patch"],
        "Infection": ["pain", "swelling", "pus", "burn", "infection"],
        "Allergy": ["allergy", "reaction", "irritation", "sensitive"],
        "Fungal Infection": ["fungal", "ringworm", "itchy circle"],
        "Normal": []
    }

    # ADVICE MAP
    advice = {
        "Acne": "Keep skin clean and avoid oily products.",
        "Eczema": "Use moisturizer and avoid harsh soaps.",
        "Infection": "Consult a doctor if pain persists.",
        "Allergy": "Avoid allergens and use soothing creams.",
        "Fungal Infection": "Keep area dry and use antifungal cream.",
        "Normal": "Your skin seems healthy."
    }

    # SEVERITY LOGIC
    severity = "Low"

    #  MATCHING LOGIC
    result = "Normal"
    match_count = 0

    for condition, keywords in conditions.items():
        count = sum(1 for word in keywords if word in text)

        if count > match_count:
            match_count = count
            result = condition

    #  CONFIDENCE CALCULATION
    confidence = round(min(0.5 + (match_count * 0.1), 0.95), 2)

    #  SEVERITY BASED ON KEYWORDS
    if match_count >= 3:
        severity = "High"
    elif match_count == 2:
        severity = "Medium"

    return jsonify({
        "input_text": text,
        "prediction": result,
        "confidence": confidence,
        "severity": severity,
        "advice": advice[result]
    })
#----------------------for image-------------------
@main.route('/analyze-image', methods=['POST'])
@jwt_required()
def analyze_image():

    if 'image' not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    file = request.files['image']

    try:
        image = Image.open(file).convert("RGB")
        image = image.resize((224, 224))

        image = np.array(image) / 255.0
        image = np.expand_dims(image, axis=0)

        prediction = model.predict(image)

        print("Prediction:", prediction)

        class_index = int(np.argmax(prediction))
        confidence = float(np.max(prediction))

        classes = [
            "Acne", "Eczema", "Melanoma",
            "Psoriasis", "Rosacea", "Normal",
            "Dermatitis", "Fungal Infection", "Warts"
        ]

        if class_index >= len(classes):
            return jsonify({"error": "Class mismatch"}), 500

        result = classes[class_index]

        # confidence check
        if confidence < 0.5:
            return jsonify({
                "prediction": "Uncertain",
                "confidence": round(confidence, 2),
                "message": "Model not confident"
            })

        return jsonify({
            "prediction": result,
            "confidence": round(confidence, 2)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500