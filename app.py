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

# --- HELPER: GET SETTINGS ---
def get_settings():
    if settings_col is None:
        return {"repo": "", "api_data": ""}
    try:
        data = settings_col.find_one({"_id": "config"})
        return data if data else {"repo": "", "api_data": ""}
    except:
        return {"repo": "", "api_data": ""}

# --- HELPER: PARSE ACCOUNTS (String to List) ---
def get_all_accounts_list(shuffle=False):
    config = get_settings()
    raw_data = config.get("api_data", "")
    
    if not raw_data:
        return []

    account_list = []
    # Line by line split karo
    lines = [line.strip() for line in raw_data.split('\n') if line.strip()]
    
    for line in lines:
        parts = line.split(',')
        if len(parts) >= 2:
            key = parts[0].strip()
            owner = parts[1].strip()
            account_list.append((key, owner))
    
    if shuffle:
        random.shuffle(account_list)
        
    return account_list

# --- ROUTES ---

@app.route('/')
def home():
    if db_error:
        return f"<h1>❌ Database Error</h1><p>{db_error}</p>"
    return "Deployer Service is Online 🟢. Go to <a href='/admin'>/admin</a>"

# --- ADMIN: SHOW PAGE ---
@app.route('/admin', methods=['GET'])
def admin():
    if 'is_admin' not in session:
        return render_template('login.html')
    
    config = get_settings()
    # List nikalo taaki table me dikha sakein
    accounts = get_all_accounts_list(shuffle=False)
    
    return render_template('admin.html', config=config, accounts=accounts)

# --- ADMIN: ADD ACCOUNT (Append Logic) ---
@app.route('/admin/add', methods=['POST'])
def admin_add():
    if 'is_admin' not in session: return redirect(url_for('login'))

    if settings_col is None: return "Database Error"

    # Form se data lo
    repo = request.form.get('repo')
    new_key = request.form.get('new_api_key').strip()
    new_owner = request.form.get('new_owner_id').strip()

    # Purana data fetch karo
    current_config = get_settings()
    current_api_data = current_config.get("api_data", "")

    # Naya data formatting (Comma laga ke)
    new_entry = f"{new_key},{new_owner}"

    # Agar pehle se data hai to nayi line me add karo, warna seedha
    if current_api_data:
        updated_api_data = current_api_data + "\n" + new_entry
    else:
        updated_api_data = new_entry

    # Save to DB
    settings_col.update_one(
        {"_id": "config"}, 
        {"$set": {"repo": repo, "api_data": updated_api_data}}, 
        upsert=True
    )
    
    return redirect(url_for('admin'))

# --- ADMIN: CLEAR ALL (Reset) ---
@app.route('/admin/clear', methods=['POST'])
def admin_clear():
    if 'is_admin' not in session: return redirect(url_for('login'))
    
    if settings_col is not None:
        settings_col.update_one(
            {"_id": "config"}, 
            {"$set": {"api_data": ""}}, # Sirf API data saaf karo, repo rehne do
            upsert=True
        )
    return redirect(url_for('admin'))

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
        # 1. Randomize karke saare accounts uthao
        accounts = get_all_accounts_list(shuffle=True)

        if not accounts:
            return jsonify({"status": "error", "message": "No Accounts found! Admin Panel me add karo."})

        json_data = request.json
        repo = json_data.get('repo')
        env_vars = json_data.get('env_vars')
        
        env_payload = [{"key": k, "value": v} for k, v in env_vars.items()]
        
        last_error = "Unknown"

        # 2. Loop through accounts
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
                print(f"🔄 Trying Key ending in...{api_key[-4:]}")
                response = requests.post("https://api.render.com/v1/services", json=payload, headers=headers)
                
                if response.status_code == 201:
                    service_data = response.json()
                    srv_id = service_data.get('service', {}).get('id')
                    dash_url = f"https://dashboard.render.com/web/{srv_id}"
                    return jsonify({"status": "success", "url": dash_url})
                
                elif response.status_code == 429:
                    print("⚠️ Rate Limit! Trying next account...")
                    last_error = "Rate Limit Exceeded"
                    continue # Next key try karo
                
                else:
                    return jsonify({"status": "error", "message": f"Render Error: {response.text}"})

            except Exception as e:
                print(f"Connection Error: {e}")
                last_error = str(e)
                continue

        return jsonify({"status": "error", "message": f"All accounts failed. Last Error: {last_error}"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(debug=True)
