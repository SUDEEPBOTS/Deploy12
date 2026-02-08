
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from pymongo import MongoClient
import requests
import os
import secrets
import traceback

app = Flask(__name__)
app.secret_key = "debug_secret_key_123"

# --- MONGODB SETUP ---
MONGO_URL = os.getenv("MONGO_URL")

client = None
db = None
settings_col = None
db_error = None

try:
    if not MONGO_URL:
        db_error = "MONGO_URL Environment Variable nahi mila! Vercel Settings check karo."
    else:
        client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
        db = client["DeployerBot"]
        settings_col = db["settings"]
        client.server_info() # Connection test
except Exception as e:
    db_error = str(e)

# --- HELPER FUNCTION ---
def get_settings():
    # 🔥 FIX: 'if not settings_col:' ko badal kar 'is None' kiya hai
    if settings_col is None:
        return {"repo": "", "api_key": "", "owner_id": ""}
    
    try:
        data = settings_col.find_one({"_id": "config"})
        if not data:
            return {"repo": "", "api_key": "", "owner_id": ""}
        return data
    except:
        return {"repo": "", "api_key": "", "owner_id": ""}

# --- ROUTES ---

@app.route('/')
def home():
    if db_error:
        return f"<h1>❌ Database Error</h1><p>{db_error}</p>"
    return "Deployer Service is Online 🟢. Go to <a href='/admin'>/admin</a>"

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    try:
        if 'is_admin' not in session:
            return render_template('login.html')
        
        if request.method == 'POST':
            repo = request.form.get('repo')
            api_key = request.form.get('api_key')
            owner_id = request.form.get('owner_id')
            
            # 🔥 FIX: Yahan bhi check lagaya
            if settings_col is not None:
                settings_col.update_one(
                    {"_id": "config"}, 
                    {"$set": {"repo": repo, "api_key": api_key, "owner_id": owner_id}}, 
                    upsert=True
                )
            return redirect(url_for('admin'))

        config = get_settings()
        return render_template('admin.html', config=config)
    
    except Exception as e:
        return f"<h1>❌ Admin Error</h1><pre>{traceback.format_exc()}</pre>"

@app.route('/login', methods=['POST'])
def login():
    if request.form.get('password') == "admin_sudeep_123":
        session['is_admin'] = True
        return redirect(url_for('admin'))
    return "Incorrect Password"

# --- API DEPLOY ROUTE (Site A se request yahan aayegi) ---
@app.route('/prepare', methods=['POST'])
def prepare():
    # Site A se jo data aaya
    data = request.form.to_dict()
    
    config = get_settings()
    # Agar user ne repo nahi bheja, toh default admin wala use karo
    repo_url = data.get('repo_url')
    if not repo_url:
        repo_url = config.get('repo', 'https://github.com/TeamYukki/YukkiMusicBot')
    
    # Clean data (repo url ko env vars se hatao)
    if 'repo_url' in data:
        del data['repo_url']

    return render_template('deploy.html', env_vars=data, repo_url=repo_url)

@app.route('/api/deploy', methods=['POST'])
def deploy_api():
    try:
        config = get_settings()
        api_key = config.get('api_key')
        owner_id = config.get('owner_id')

        if not api_key:
            return jsonify({"status": "error", "message": "Admin ne Render API Key set nahi ki hai!"})

        json_data = request.json
        repo = json_data.get('repo')
        env_vars = json_data.get('env_vars')

        # 1. Env Vars Format
        env_payload = []
        for key, value in env_vars.items():
            env_payload.append({"key": key, "value": value})

        # 2. Render Payload
        payload = {
            "serviceDetails": {
                "type": "web_service",
                "name": f"music-bot-{secrets.token_hex(3)}",
                "repo": repo,
                "env": "docker",
                "region": "singapore",
                "plan": "free",
                "envVars": env_payload
            }
        }
        
        if owner_id:
            payload["serviceDetails"]["ownerId"] = owner_id

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        url = "https://api.render.com/v1/services"
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 201:
            service_data = response.json()
            srv_id = service_data.get('service', {}).get('id')
            dash_url = f"https://dashboard.render.com/web/{srv_id}"
            return jsonify({"status": "success", "url": dash_url})
        else:
            return jsonify({"status": "error", "message": f"Render Error: {response.text}"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(debug=True)
