from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from pymongo import MongoClient
import requests
import os
import secrets

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- MONGODB CONNECTION ---
# Render Environment Variable me 'MONGO_URL' dalna mat bhulna
MONGO_URL = os.getenv("MONGO_URL")

try:
    if MONGO_URL:
        client = MongoClient(MONGO_URL)
        db = client["DeployerBot"]
        settings_col = db["settings"]
        print("✅ MongoDB Connected")
    else:
        print("⚠️ MONGO_URL not found!")
        settings_col = None
except Exception as e:
    print(f"❌ MongoDB Error: {e}")

# --- ADMIN PASSWORD ---
# Ise change kar lena
ADMIN_PASSWORD = "admin_sudeep_123"

def get_settings():
    if not settings_col:
        return {"repo": "", "api_key": "", "owner_id": ""}
    
    data = settings_col.find_one({"_id": "config"})
    if not data:
        return {"repo": "https://github.com/TeamYukki/YukkiMusicBot", "api_key": "", "owner_id": ""}
    return data

@app.route('/')
def home():
    return "Deployer Service is Online 🟢. Go to /admin to configure."

# --- STEP 1: RECEIVE DATA FROM SITE A ---
@app.route('/prepare', methods=['POST'])
def prepare():
    # Site A se data yahan aayega
    data = request.form.to_dict()
    
    # Agar Site A se Repo URL aaya hai toh wo use karo, warna Default
    config = get_settings()
    repo_url = data.get('repo_url', config['repo'])
    
    # 'repo_url' ko env vars me se hata do taaki .env me na jaye
    if 'repo_url' in data:
        del data['repo_url']

    return render_template('deploy.html', env_vars=data, repo_url=repo_url)

# --- STEP 2: DEPLOY TO RENDER (API CALL) ---
@app.route('/api/deploy', methods=['POST'])
def deploy_api():
    config = get_settings()
    api_key = config.get('api_key')
    owner_id = config.get('owner_id') # Render Owner ID (Optional but recommended)

    if not api_key:
        return jsonify({"status": "error", "message": "Admin ne Render API Key set nahi ki hai!"})

    json_data = request.json
    repo = json_data.get('repo')
    env_vars = json_data.get('env_vars')

    # 1. Environment Variables ko Render format me convert karo
    env_payload = []
    for key, value in env_vars.items():
        env_payload.append({"key": key, "value": value})

    # 2. Render API Payload (Docker Mode)
    # Music bots ke liye 'docker' best hai. Start Command ki zaroorat nahi padegi.
    payload = {
        "serviceDetails": {
            "type": "web_service",
            "name": f"music-bot-{secrets.token_hex(3)}",
            "repo": repo,
            "env": "docker",  # YAHAN DOCKER SET KIYA HAI
            "region": "singapore", # ya 'oregon', 'frankfurt'
            "plan": "free",
            "envVars": env_payload
        }
    }
    
    # Agar Owner ID hai toh add karo (Team accounts ke liye zaroori hota hai)
    if owner_id:
        payload["serviceDetails"]["ownerId"] = owner_id

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    try:
        url = "https://api.render.com/v1/services"
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 201:
            service_data = response.json()
            # Service ID mil gayi
            srv_id = service_data.get('service', {}).get('id')
            # Dashboard link banao
            dash_url = f"https://dashboard.render.com/web/{srv_id}"
            return jsonify({"status": "success", "url": dash_url})
        else:
            return jsonify({"status": "error", "message": f"Render API Error: {response.text}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# --- ADMIN PANEL ---
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'is_admin' not in session:
        return render_template('login.html')
    
    if request.method == 'POST':
        repo = request.form.get('repo')
        api_key = request.form.get('api_key')
        owner_id = request.form.get('owner_id')
        
        if settings_col:
            settings_col.update_one(
                {"_id": "config"}, 
                {"$set": {"repo": repo, "api_key": api_key, "owner_id": owner_id}}, 
                upsert=True
            )
        return redirect(url_for('admin'))

    config = get_settings()
    return render_template('admin.html', config=config)

@app.route('/login', methods=['POST'])
def login():
    if request.form.get('password') == ADMIN_PASSWORD:
        session['is_admin'] = True
        return redirect(url_for('admin'))
    return "Incorrect Password"

if __name__ == '__main__':
    app.run(debug=True)
           
