import requests
import json
from app import app, db
from dotenv import load_dotenv

crm = requests.get("https://app.onepagecrm.com/api/v3/action_stream?team=true&action_stream=true&page=5&per_page=20", auth=(app.config['ONEPAGECRM_ID'], app.config['ONEPAGECRM_PW']))
print(json.dumps(crm.json(), indent=2))