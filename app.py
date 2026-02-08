from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from pymongo import MongoClient
import requests
import os
import secrets
import traceback
import random

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
        client.server_info()
except Exception as e:
    db_error = str(e)

# --- HELPER: SETTINGS ---
def get_settings():
    if settings_col is None:
        return {"repo": "", "api_data": ""}
    try:
        data = settings_col.find_one({"_id": "config"})
        return data if data else {"repo": "", "api_data": ""}
    except:
        return {"repo": "", "api_data": ""}

# --- HELPER: GET ALL ACCOUNTS (List) ---
def get_all_accounts():
    config = get_settings()
    raw_data = config.get("api_data", "")
    
    if not raw_data:
        return []

    account_list = []
    lines = [line.strip() for line in raw_data.split('\n') if line.strip()]
    
    for line in lines:
        parts = line.split(',')
        if len(parts) >= 2:
            key = parts[0].strip()
            owner = parts[1].strip()
            account_list.append((key, owner))
    
    # List ko Randomize kar do taaki har baar pehli key par load na pade
    random.shuffle(account_list)
    return account_list

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
            api_data = request.form.get('api_data')
            
            if settings_col is not None:
                settings_col.update_one(
                    {"_id": "config"}, 
                    {"$set": {"repo": repo, "api_data": api_data}}, 
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

@app.route('/prepare', methods=['POST'])
def prepare():
    data = request.form.to_dict()
    config = get_settings()
    repo_url = data.get('repo_url')
    if not repo_url:
        repo_url = config.get('repo', 'https://github.com/TeamYukki/YukkiMusicBot')
    
    if 'repo_url' in data: del data['repo_url']
    return render_template('deploy.html', env_vars=data, repo_url=repo_url)

@app.route('/api/deploy', methods=['POST'])
def deploy_api():
    try:
        # 1. Saare Accounts ki list uthao
        accounts = get_all_accounts()

        if not accounts:
            return jsonify({"status": "error", "message": "No API Keys found in Admin Panel!"})

        json_data = request.json
        repo = json_data.get('repo')
        env_vars = json_data.get('env_vars')
        
        env_payload = [{"key": k, "value": v} for k, v in env_vars.items()]
        
        last_error_message = "Unknown Error"
        
        # 2. LOOP START: Ek-ek karke try karo
        for api_key, owner_id in accounts:
            
            payload = {
                "serviceDetails": {
                    "type": "web_service",
                    "name": f"music-bot-{secrets.token_hex(3)}",
                    "repo": repo,
                    "env": "docker",
                    "region": "singapore",
                    "plan": "free",
                    "ownerId": owner_id,
                    "envVars": env_payload
                }
            }
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }

            try:
                print(f"🔄 Trying Key: {api_key[:5]}... Owner: {owner_id}")
                response = requests.post("https://api.render.com/v1/services", json=payload, headers=headers)
                
                # --- CASE 1: SUCCESS (201) ---
                if response.status_code == 201:
                    service_data = response.json()
                    srv_id = service_data.get('service', {}).get('id')
                    dash_url = f"https://dashboard.render.com/web/{srv_id}"
                    return jsonify({"status": "success", "url": dash_url})
                
                # --- CASE 2: RATE LIMIT (429) ---
                elif response.status_code == 429:
                    print(f"⚠️ Rate Limit on Key {api_key[:5]}... Switching to Next Key.")
                    last_error_message = "Rate Limit Exceeded on all keys."
                    continue # Loop wapas chalega agli key ke sath
                
                # --- CASE 3: OTHER ERROR (Repo error, invalid name, etc.) ---
                else:
                    # Agar error rate limit nahi hai (jaise Invalid Repo), toh agla try karne ka faida nahi
                    return jsonify({"status": "error", "message": f"Render Error: {response.text}"})

            except Exception as e:
                print(f"❌ Connection Error: {str(e)}")
                last_error_message = str(e)
                continue # Network error hua toh bhi next key try karo

        # 3. Agar loop khatam ho gaya aur success nahi mili
        return jsonify({"status": "error", "message": f"All API Keys Failed. Last Error: {last_error_message}"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(debug=True)
